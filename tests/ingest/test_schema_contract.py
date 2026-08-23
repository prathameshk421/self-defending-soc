"""The checked-in schema files must byte-equal what the models generate."""

from ingest.schema_gen import SCHEMA_MODELS, generate_schema_text, packaged_schema_text


def test_checked_in_schemas_match_models():
    for filename, model in SCHEMA_MODELS.items():
        checked_in = packaged_schema_text(filename)
        generated = generate_schema_text(model)
        assert checked_in == generated, (
            f"{filename} is stale: run `ingest schema export` and commit the result"
        )


def test_every_subject_maps_to_a_known_file():
    from ingest.schema_gen import SUBJECT_SCHEMAS

    for subject, filename in SUBJECT_SCHEMAS.items():
        assert filename in SCHEMA_MODELS
