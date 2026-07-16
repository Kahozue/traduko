from traduko.sync.merge import merge_glossary, parse_rows, render_rows

HEADER = "source,target,notes,scope\r\n"


def csv_text(*rows: str) -> str:
    return HEADER + "".join(row + "\r\n" for row in rows)


def test_parse_and_render_round_trip_sorted() -> None:
    rows = parse_rows(csv_text("beta,B,,", "alpha,A,note,proj"))
    assert rows["alpha"] == {
        "source": "alpha", "target": "A", "notes": "note", "scope": "proj"
    }
    rendered = render_rows(rows)
    assert rendered.splitlines()[0] == "source,target,notes,scope"
    assert rendered.index("alpha") < rendered.index("beta")


def test_one_side_addition_and_edit_win() -> None:
    base = csv_text("kept,K,,")
    local = csv_text("kept,K-edited,,", "added-local,L,,")
    remote = csv_text("kept,K,,", "added-remote,R,,")
    merged, conflicts = merge_glossary(base, local, remote)
    rows = parse_rows(merged)
    assert conflicts == []
    assert rows["kept"]["target"] == "K-edited"
    assert rows["added-local"]["target"] == "L"
    assert rows["added-remote"]["target"] == "R"


def test_both_sides_same_change_is_not_a_conflict() -> None:
    base = csv_text("term,old,,")
    both = csv_text("term,new,,")
    merged, conflicts = merge_glossary(base, both, both)
    assert conflicts == []
    assert parse_rows(merged)["term"]["target"] == "new"


def test_diverging_edits_conflict_and_keep_local() -> None:
    base = csv_text("term,old,,")
    local = csv_text("term,mine,,")
    remote = csv_text("term,theirs,,")
    merged, conflicts = merge_glossary(base, local, remote)
    assert parse_rows(merged)["term"]["target"] == "mine"
    assert conflicts == [
        {
            "source": "term",
            "local": {"source": "term", "target": "mine", "notes": "", "scope": ""},
            "remote": {"source": "term", "target": "theirs", "notes": "", "scope": ""},
        }
    ]


def test_deletions_do_not_propagate() -> None:
    base = csv_text("term,T,,")
    local = HEADER
    remote = csv_text("term,T,,")
    merged, conflicts = merge_glossary(base, local, remote)
    assert conflicts == []
    assert parse_rows(merged)["term"]["target"] == "T"
