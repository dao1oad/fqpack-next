def test_db_module_exposes_screening_database():
    import freshquant.db as db_module

    assert hasattr(db_module, "DBScreening")
    assert db_module.get_db("screening") is db_module.DBScreening
