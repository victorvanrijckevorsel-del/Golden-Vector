import pytest

from golden_vector.hedge.holdings import Holding, load_holdings
from tests.helpers import build_test_paths


def test_load_holdings_missing_file_returns_empty_list(tmp_path):
    paths = build_test_paths(tmp_path)

    assert load_holdings(paths) == []


def test_load_holdings_reads_mixed_share_and_dollar_exposure_entries(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.manual_holdings_dir.mkdir(parents=True)
    paths.holdings_path.write_text(
        """
version: 1
holdings:
  - ticker: aem
    shares: 200
  - ticker: NEM
    dollar_exposure: 50000
""".lstrip(),
        encoding="utf-8",
    )

    holdings = load_holdings(paths)

    assert holdings == [
        Holding(ticker="AEM", shares=200.0, dollar_exposure=None),
        Holding(ticker="NEM", shares=None, dollar_exposure=50000.0),
    ]


@pytest.mark.parametrize(
    "body,match",
    [
        ("[]\n", "mapping"),
        ("holdings: nope\n", "must be a list"),
        ("holdings:\n  - ticker: AEM\n", "exactly one"),
        ("holdings:\n  - ticker: AEM\n    shares: 0\n", "positive"),
        ("holdings:\n  - ticker: AEM\n    shares: 1\n    dollar_exposure: 2\n", "exactly one"),
        ("holdings:\n  - shares: 1\n", "ticker"),
    ],
)
def test_load_holdings_rejects_malformed_entries(tmp_path, body, match):
    paths = build_test_paths(tmp_path)
    paths.manual_holdings_dir.mkdir(parents=True)
    paths.holdings_path.write_text(body, encoding="utf-8")

    with pytest.raises(ValueError, match=match):
        load_holdings(paths)


def test_holding_exposure_uses_dollar_exposure_or_share_price():
    assert Holding(ticker="AEM", dollar_exposure=5000).exposure_usd(share_price=None) == 5000
    assert Holding(ticker="AEM", shares=10).exposure_usd(share_price=50) == 500
    assert Holding(ticker="AEM", shares=10).exposure_usd(share_price=None) is None
