import httpx
import pytest

from cart_mcp import cache as cache_mod
from cart_mcp import sda

SAMPLE_XML = """<?xml version="1.0" encoding="utf-8"?>
<NewDataSet>
  <xs:schema id="NewDataSet" xmlns="" xmlns:xs="http://www.w3.org/2001/XMLSchema"/>
  <Table>
    <landunit>T9981 Fld3</landunit>
    <rating_name>Agricultural Organic Soil Subsidence</rating_name>
    <rating_value>4</rating_value>
    <rating_class>Mineral soil</rating_class>
    <soils_metadata>ND001 2018-09-12 19:21:50 | SD105 2018-09-12 23:49:29</soils_metadata>
  </Table>
  <Table>
    <landunit>T9981 Fld3</landunit>
    <rating_name>Soil Organic Carbon Stock</rating_name>
    <rating_value>4</rating_value>
    <rating_class>Moderate</rating_class>
    <soils_metadata />
  </Table>
</NewDataSet>
"""

SERVICE_EXCEPTION = """<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<ServiceExceptionReport xmlns="http://www.opengis.net/ogc">
<ServiceException>post.rest error: something broke</ServiceException>
</ServiceExceptionReport>
"""


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_mod.clear_cache()
    yield
    cache_mod.clear_cache()


def _response(status: int, text: str) -> httpx.Response:
    return httpx.Response(
        status,
        text=text,
        request=httpx.Request("POST", "https://sdmdataaccess.nrcs.usda.gov/tabular/post.rest"),
    )


def test_parse_xml_rows(monkeypatch):
    def fake_post(*args, **kwargs):
        return _response(200, SAMPLE_XML)

    monkeypatch.setattr(httpx, "post", fake_post)
    result = sda.submit("SELECT 1")
    assert result.row_count == 2
    assert result.columns == [
        "landunit",
        "rating_name",
        "rating_value",
        "rating_class",
        "soils_metadata",
    ]
    assert result.rows[0]["rating_value"] == 4
    assert result.rows[1]["soils_metadata"] is None


def test_service_exception_raised(monkeypatch):
    def fake_post(*args, **kwargs):
        return _response(200, SERVICE_EXCEPTION)

    monkeypatch.setattr(httpx, "post", fake_post)
    with pytest.raises(sda.SDAError, match="something broke"):
        sda.submit("SELECT 1")


def test_http_error_raised(monkeypatch):
    def fake_post(*args, **kwargs):
        return _response(500, "boom")

    monkeypatch.setattr(httpx, "post", fake_post)
    with pytest.raises(sda.SDAError):
        sda.submit("SELECT 1")


def test_parse_ratings_normalizes():
    result = sda._parse_xml(SAMPLE_XML)
    ratings = sda.parse_ratings(result)
    assert ratings[0]["rating_value"] == 4
    assert ratings[0]["rating_class"] == "Mineral soil"
    assert ratings[0]["landunit"] == "T9981 Fld3"


EMPTY_XML = """<?xml version="1.0" encoding="utf-8"?>
<NewDataSet>
  <xs:schema id="NewDataSet" xmlns="" xmlns:xs="http://www.w3.org/2001/XMLSchema"/>
</NewDataSet>
"""


def test_empty_rows_raises_clear_error(monkeypatch):
    def fake_post(*args, **kwargs):
        return _response(200, EMPTY_XML)

    monkeypatch.setattr(httpx, "post", fake_post)
    with pytest.raises(sda.SDAError, match="no rows"):
        sda.submit("SELECT 1")


def test_retry_succeeds_after_transient_503(monkeypatch):
    calls = {"n": 0}

    def fake_post(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return _response(503, "unavailable")
        return _response(200, SAMPLE_XML)

    monkeypatch.setattr(httpx, "post", fake_post)
    result = sda._submit_with_retry("SELECT 1", sda.SDA_ENDPOINT, sda.SDA_TIMEOUT)
    assert result.row_count == 2
    assert calls["n"] == 2


def test_service_exception_not_retried(monkeypatch):
    calls = {"n": 0}

    def fake_post(*args, **kwargs):
        calls["n"] += 1
        return _response(200, SERVICE_EXCEPTION)

    monkeypatch.setattr(httpx, "post", fake_post)
    with pytest.raises(sda.SDAError, match="something broke"):
        sda._submit_with_retry("SELECT 1", sda.SDA_ENDPOINT, sda.SDA_TIMEOUT)
    assert calls["n"] == 1


def test_cache_hit_avoids_second_request(monkeypatch):
    calls = {"n": 0}

    def fake_post(*args, **kwargs):
        calls["n"] += 1
        return _response(200, SAMPLE_XML)

    monkeypatch.setattr(httpx, "post", fake_post)
    first = sda.submit("SELECT CACHE_ME")
    second = sda.submit("SELECT CACHE_ME")
    assert first.row_count == second.row_count == 2
    assert calls["n"] == 1
