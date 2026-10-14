from app.query_expansion import expand_query


def test_unmatched_question_is_unchanged():
    assert expand_query("What is my deductible?") == "What is my deductible?"


def test_original_question_is_preserved_and_terms_appended():
    expanded = expand_query("Is a nose job covered?")
    assert expanded.startswith("Is a nose job covered?")
    assert "cosmetic surgery" in expanded


def test_brand_drug_names_map_to_generic_class():
    assert "GLP-1" in expand_query("Is Wegovy covered?")


def test_multiple_matches_are_all_added_once():
    expanded = expand_query("I broke a tooth abroad, will a dentist abroad be covered?")
    assert expanded.count("dental care") == 1
    assert "outside the United States" in expanded


def test_word_boundaries_avoid_false_matches():
    # "er" inside "covered" or "pt" inside "except" must not trigger
    assert expand_query("Is this covered except for weekends?") == "Is this covered except for weekends?"
