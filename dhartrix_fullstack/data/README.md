# DHARTRIX reference datasets

`disease_reference_template.csv` is a small **schema/template**, not a comprehensive disease database and not model-training data. The examples are illustrative and must be checked against trusted local agricultural sources before operational use. Replace `REPLACE_WITH_VERIFIED_SOURCE`, record the source and licence, and review each row before publishing recommendations.

The Disease Detection page can load a CSV from the user's computer and search its text fields. This feature does not classify image pixels. A real image classifier needs a trained model, compatible preprocessing, validation on independent field images, and a backend inference endpoint.

Recommended columns: `crop,disease,symptoms,prevention,organic_practices,source,license`. You can add fields such as scientific name, region, pathogen, confidence/evidence, date reviewed and reviewer.
