-- CART MCP: AOI risk map for ONE cointerp-based resource concern.
-- Per-polygon geometry clipped to the AOI, carrying the rating of the dominant
-- major soil component per map unit (Order 5 map units are rated Not rated).
-- Mirrors the kitchensink pipeline stages 0-1, #AllOrder6, #SDV rulekey lookup,
-- and the #M5 cointerp join; the concern attributename is injected at build
-- time from validated embedded data.

~DeclareGeometry(@aoiGeom)~
~DeclareGeometry(@aoiGeomFixed)~
~DeclareChar(@attributeName,60)~
~DeclareInt(@ruleKey)~

CREATE TABLE #AoiTable
    ( aoiid INT IDENTITY (1,1),
    landunit CHAR(20),
    aoigeom GEOMETRY )
;

-- Insert identifier string and WKT geometry for each AOI polygon after this...
-- BEGIN AOI SECTION (generated)
-- This line below is replaced at runtime with parameterized, validated
-- EPSG:4326 geometries:
{AOI_SECTION}
-- END AOI SECTION (generated)

CREATE TABLE #AoiSoils
    ( aoiid INT,
    landunit CHAR(20),
    mukey INT,
    soilgeom GEOMETRY )
;

CREATE TABLE #AoiSoils2
    ( aoiid INT,
    landunit CHAR(20),
    mukey INT,
    poly_acres FLOAT,
    soilgeog GEOGRAPHY )
;

CREATE TABLE #M2
    ( aoiid INT,
    landunit CHAR(20),
    mukey INT,
    mapunit_acres FLOAT )
;

CREATE TABLE #AllOrder6
    ( landunit CHAR(20),
    mukey INT,
    is_order5 INT )
;

CREATE TABLE #M4
    ( aoiid INT,
    landunit CHAR(20),
    mukey INT,
    mapunit_acres FLOAT,
    cokey INT,
    compname CHAR(60),
    comppct_r INT,
    majcompflag CHAR(3),
    mu_pct_sum INT )
;

CREATE TABLE #M5
    ( aoiid INT,
    landunit CHAR(20),
    mukey INT,
    mapunit_acres FLOAT,
    cokey INT,
    compname CHAR(60),
    comppct_r INT,
    rating_value FLOAT,
    rating_class CHAR(60) )
;

CREATE TABLE #DomRating
    ( landunit CHAR(20),
    mukey INT,
    rating_value FLOAT,
    rating_class CHAR(60) )
;

INSERT INTO #AoiSoils (aoiid, landunit, mukey, soilgeom)
    SELECT A.aoiid, A.landunit, M.mukey, M.mupolygongeo.STIntersection(A.aoigeom) AS soilgeom
    FROM #AoiTable A
    INNER JOIN mupolygon M ON M.mupolygongeo.STIntersects(A.aoigeom) = 1
    WHERE M.mupolygongeo.STIsValid() = 1
;

INSERT INTO #AoiSoils2 (aoiid, landunit, mukey, poly_acres, soilgeog)
    SELECT aoiid, landunit, mukey,
        ROUND((GEOGRAPHY::STGeomFromWKB(soilgeom.STAsBinary(), 4326).MakeValid().STArea()) / 4046.8564224, 3) AS poly_acres,
        GEOGRAPHY::STGeomFromWKB(soilgeom.STAsBinary(), 4326).MakeValid() AS soilgeog
    FROM #AoiSoils
;

INSERT INTO #M2 (aoiid, landunit, mukey, mapunit_acres)
    SELECT DISTINCT aoiid, landunit, mukey,
        ROUND(SUM(poly_acres) OVER(PARTITION BY landunit, mukey), 3) AS mapunit_acres
    FROM #AoiSoils2
    GROUP BY aoiid, landunit, mukey, poly_acres
;

INSERT INTO #AllOrder6 (landunit, mukey, is_order5)
    SELECT #M2.landunit, #M2.mukey,
        CASE WHEN COUNT(*) = SUM(CASE WHEN invesintens = 'Order 5' THEN 1 ELSE 0 END)
             THEN 1 ELSE 0 END AS is_order5
    FROM #M2
    INNER JOIN mapunit ON mapunit.mukey = #M2.mukey
    GROUP BY #M2.landunit, #M2.mukey
;

SELECT @attributeName = '{ATTRIBUTE_NAME}';
SELECT @ruleKey = (SELECT TOP 1 md.rulekey
    FROM distinterpmd md
    LEFT OUTER JOIN sdvattribute sdv ON sdv.nasisrulename = md.rulename
    WHERE sdv.attributename = @attributeName);

INSERT INTO #M4 (aoiid, landunit, mukey, mapunit_acres, cokey, compname, comppct_r, majcompflag, mu_pct_sum)
    SELECT M2.aoiid, M2.landunit, M2.mukey, M2.mapunit_acres,
           CO.cokey, CO.compname, CO.comppct_r, CO.majcompflag,
           SUM(CO.comppct_r) OVER(PARTITION BY M2.landunit, M2.mukey) AS mu_pct_sum
    FROM #M2 AS M2
    INNER JOIN component AS CO ON CO.mukey = M2.mukey
;

INSERT INTO #M5 (aoiid, landunit, mukey, mapunit_acres, cokey, compname, comppct_r, rating_value, rating_class)
    SELECT M4.aoiid, M4.landunit, M4.mukey, M4.mapunit_acres, M4.cokey, M4.compname, M4.comppct_r,
           TP.interphr AS rating_value, TP.interphrc AS rating_class
    FROM #M4 AS M4
    LEFT OUTER JOIN cointerp AS TP ON M4.cokey = TP.cokey AND TP.rulekey = @ruleKey AND TP.ruledepth = 0
    WHERE M4.majcompflag = 'Yes'
;

INSERT INTO #DomRating (landunit, mukey, rating_value, rating_class)
    SELECT t.landunit, t.mukey,
        CASE WHEN o6.is_order5 = 1 THEN NULL ELSE t.rating_value END AS rating_value,
        CASE WHEN o6.is_order5 = 1 THEN 'Not rated' ELSE t.rating_class END AS rating_class
    FROM (
        SELECT landunit, mukey, rating_value, rating_class,
               ROW_NUMBER() OVER(PARTITION BY landunit, mukey ORDER BY comppct_r DESC, cokey ASC) AS rn
        FROM #M5
    ) t
    LEFT OUTER JOIN #AllOrder6 o6 ON t.landunit = o6.landunit AND t.mukey = o6.mukey
    WHERE t.rn = 1
;

SELECT D.landunit, S.mukey, MU.musym, MU.muname, MU.invesintens,
       S.poly_acres, D.rating_value, D.rating_class, S.soilgeog.STAsText() AS geom_wkt
FROM #AoiSoils2 AS S
INNER JOIN #DomRating D ON S.landunit = D.landunit AND S.mukey = D.mukey
INNER JOIN mapunit MU ON MU.mukey = S.mukey
ORDER BY S.landunit, S.mukey, S.poly_acres DESC
;
