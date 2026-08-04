-- CART MCP: lightweight AOI soil summary (map units + major components, no ratings).
-- Mirrors shared pipeline stage 1 (#AoiTable -> #AoiSoils -> #AoiSoils2 -> #M2) from the
-- CART kitchensink query, then joins mapunit/component for an inspectable snapshot.

~DeclareGeometry(@aoiGeom)~
~DeclareGeometry(@aoiGeomFixed)~

CREATE TABLE #AoiTable
    ( aoiid INT IDENTITY (1,1),
    landunit CHAR(20),
    aoigeom GEOMETRY )
;

-- Insert identifier string and WKT geometry for each AOI polygon after this...
-- BEGIN AOI SECTION (generated)
-- {AOI_SECTION} is replaced at runtime with parameterized, validated EPSG:4326 geometries.
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

SELECT S.landunit, S.mukey, MU.musym, MU.muname, MU.invesintens, MU.farmlndcl,
       S.mapunit_acres, CO.cokey, CO.compname, CO.comppct_r, CO.majcompflag, CO.drainagecl
FROM #M2 AS S
INNER JOIN mapunit MU ON MU.mukey = S.mukey
INNER JOIN component CO ON CO.mukey = S.mukey AND CO.majcompflag = 'Yes'
ORDER BY S.landunit, S.mukey, CO.comppct_r DESC
;
