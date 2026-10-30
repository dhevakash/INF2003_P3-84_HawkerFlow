# Data and provenance

| File/data | Origin | Use |
|---|---|---|
| `raw/nea_hawker_centres.csv` | Supplied historical NEA/data.gov.sg snapshot, 107 records | First five addresses locate fictional HawkerFlow branches; no claim those centres operate a real chain |
| `raw/uci_sentiment_readme.txt` | Supplied UCI dataset documentation | Attribution and format only; it does not contain review sentences |
| `yelp_labelled.txt` | Must still be obtained from the UCI Sentiment Labelled Sentences dataset | Optional external_examples collection; 1,000 restaurant-review sentences with binary sentiment |
| Operational SQL records and purchase reviews | Generated for this project | Synthetic recipes, prices, stock, customers, sales and feedback |

NEA source identified by the progress report: data.gov.sg dataset `d_68a42f09f350881996d83f9cd73ab02f`. Dataset ID is retained as supplied provenance; this package does not claim a current-source refresh.

UCI reference: D. Kotzias, Sentiment Labelled Sentences, UCI Machine Learning Repository, 2015, DOI https://doi.org/10.24432/C57604. Also follow the supplied readme's request to cite Kotzias et al., "From Group to Individual Labels using Deep Features," KDD 2015. Verify the source's current licence and retain it when obtaining the actual sentences.

Import the actual file after initializing MongoDB:

```powershell
python -m app.cli import-uci --file data/raw/yelp_labelled.txt
```

For Docker, copy it first: `docker compose cp data/raw/yelp_labelled.txt app:/code/data/raw/yelp_labelled.txt`, then run the same command through `docker compose exec app`.

Synthetic base data uses seed 20261002; order generation uses deterministic substream seed 20261003. Opening stock is dated 1 July 2026; the 200 generated sales cover dates in July-October 2026. Review text is explicitly labelled synthetic. Real addresses do not authenticate fictional reviews. No UCI sentence receives an invented customer/order/branch identifier.
