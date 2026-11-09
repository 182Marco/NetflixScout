from __future__ import annotations

from pipelines.wikipedia_series import extract_series as ex
from pipelines.wikipedia_series import tv_movies as tm

TABLE = """intro
{| class="wikitable"
! nº
! Titolo originale
! Titolo italiano
! Prima TV USA
|-
| 1 || ''Pilot'' || [[#Inizio|Inizio]] || rowspan="2"| 30 maggio 2017
|-
| 2 || ''Second'' || Secondo
|}
"""


def page(pid, title, text):
    return {"id": pid, "ns": 0, "title": title, "rev": pid * 10, "kind": "article", "text": text}


def run(pages):
    return ex.process(lambda: iter(pages))


def test_clean_param_resolves_links():
    assert tm.clean_param("[[Lingua inglese|inglese]] <!--x-->") == "inglese"


def test_table_rows_with_header_roles_and_partial_rows():
    rows = ex.episode_rows(TABLE)
    assert [r.get("number_int") for r in rows] == [1, 2]
    assert rows[0]["title_original"] == "Pilot" and rows[0]["title_it"] == "Inizio"
    assert rows[0]["dates"] == ["30 maggio 2017"]
    assert rows[1].get("partial") and "dates" not in rows[1]  # shorter than the header: never aligned by guessing


def test_season_page_yields_hints_and_episode_sections():
    text = ("{{torna a|Serie X}}\nLa stagione.\n" + TABLE + "\n== Pilot ==\n* Diretto da: A\n=== Trama ===\n" + "Una trama molto lunga. " * 12 + "\n")
    out, _ = run([page(1, "Episodi di Serie X (seconda stagione)", text)])
    season = out["seasons"][0]
    assert season["season_number"] == 2 and season["torna_a"] == "Serie X" and season["table_row_count"] == 2
    assert out["episodes"][0]["title"] == "Pilot" and out["episodes"][0]["parent_page_id"] == 1
    assert out["episodes"][0]["plot_text"].startswith("Una trama")


def test_series_text_kind_and_subtype():
    plot = "Una storia molto lunga e dettagliata. " * 30
    text = "{{FictionTV\n|tipo fiction = miniserie tv\n|anno prima visione = 2019\n|genere = drammatico\n}}\nIntro.\n== Trama ==\n" + plot
    out, _ = run([page(2, "Una miniserie", text)])
    rec = out["series"][0]
    assert rec["subtype"] == "miniseries" and rec["text_kind"] == "plot" and rec["info"]["year"] == 2019


def test_tv_movie_is_autonomous_and_documentary_is_excluded_with_reason():
    movie = "{{FictionTV\n|tipo fiction = film TV\n|regista = A\n|attori = * B\n|genere = thriller\n}}\nUn film."
    doc = "{{FictionTV\n|tipo fiction = film TV\n|regista = A\n|attori = * B\n|genere = documentario\n}}\nUn doc."
    out, _ = run([page(3, "Un film", movie), page(4, "Un doc", doc)])
    assert [r["record_id"] for r in out["tv_movies"]] == ["wp-3"]
    assert "parent_page_id" not in out["tv_movies"][0]
    assert out["excluded"][0]["reason"] == "non_narrative_tv_movie"
    assert out["series"] == []  # a TV movie never becomes a series


def test_programme_kept_only_when_episodic_or_narrative():
    show = "{{Programma\n|genere = talk show\n}}\nUn talk."
    sitcom = "{{Programma\n|genere = commedia\n}}\nUna cosa."
    sketch = "{{Programma\n|genere = sketch\n}}\nUna cosa."
    out, _ = run([page(5, "Talk", show), page(6, "Comica", sitcom), page(7, "Sketch", sketch)])
    assert [r["page_id"] for r in out["series"]] == [6]
    assert [r["page_id"] for r in out["uncertain"]] == [7]
    assert out["excluded"][0]["reason"] == "programme_not_episodic"


def test_deterministic_order_and_unknown_pages_excluded():
    out, _ = run([page(9, "B", "testo"), page(8, "A", "testo")])
    assert [r["page_id"] for r in out["excluded"]] == [8, 9]


def test_manga_plus_anime_page_is_a_series_marked_mixed_media():
    text = ("{{Fumetto e animazione\n|tipo = manga\n|titolo = G\n}}\n{{Fumetto e animazione\n|tipo = anime\n|sottotipo = serie TV\n"
            "|episodi = 24\n}}\nIl manga G e il suo anime.\n== Trama ==\n" + "Una storia lunga. " * 40)
    out, stats = run([page(11, "G (manga)", text)])
    rec = out["series"][0]
    assert rec["subtype"] == "anime" and rec["mixed_media"] is True and rec["info"]["episodi"] == "24"
    assert stats["animation_mixed_media"] == 1


def test_pure_manga_and_anime_film_are_excluded():
    manga = "{{Fumetto e animazione\n|tipo = manga\n}}\nSolo un manga."
    film = "{{Fumetto e animazione\n|tipo = anime\n|sottotipo = film\n}}\nUn film."
    out, _ = run([page(12, "M", manga), page(13, "F", film)])
    assert out["series"] == [] and [e["reason"] for e in out["excluded"]] == ["manga_or_other_animation"] * 2


def test_episode_metadata_lines_are_cut_from_the_plot():
    prose = "Titolo originale: Abandoned Episodio dedicato a: Shannon\n\nSceneggiatura: X\nÈ sera. La storia vera e propria."
    plot, meta = ex.strip_episode_metadata(prose)
    assert plot == "È sera. La storia vera e propria." and len(meta) == 2
    assert ex.strip_episode_metadata("Data la situazione, i due partono.")[0] == "Data la situazione, i due partono."  # prose starting with "Data" stays
