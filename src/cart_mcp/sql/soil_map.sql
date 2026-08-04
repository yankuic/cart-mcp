-- CART MCP: AOI soil map (per-polygon geometry clipped to the AOI, no ratings).
-- Mirrors the shared stage-1 pattern of the kitchensink query, then emits each
-- intersected soil polygon WKT geometry for client-side map rendering.

~DeclareGeometry(@aoiGeom)~
~DeclareGeometry(@aoiGeomFixed)~

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

SELECT S.landunit, S.mukey, MU.musym, MU.muname, MU.invesintens, MU.farmlndcl,
       S.poly_acres, S.soilgeog.STAsText() AS geom_wkt
FROM #AoiSoils2 AS S
INNER JOIN mapunit MU ON MU.mukey = S.mukey
ORDER BY S.landunit, S.mukey, S.poly_acres DESC
;
