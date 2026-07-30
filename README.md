# NDIS Behaviour Support Plan De-identifier

A drag-and-drop desktop app (Windows + macOS) that takes NDIS Behaviour
Support Plan `.docx` files and produces a de-identified copy with the same
formatting, headings and tables intact - only the identifying text is
replaced with a placeholder tag like `[PARTICIPANT NAME]` or `[NDIS NUMBER]`.

Built on top of [Microsoft/data-privacy-stack Presidio](../README.MD)
(`presidio-analyzer` + spaCy NER) for PII detection, plus custom recognizers
and an Australia/NDIS-specific ruleset for the parts Presidio doesn't cover
out of the box.

## What gets redacted

| Placeholder | Source |
|---|---|
| `[PARTICIPANT NAME]`, `[GUARDIAN NAME]`, `[PRACTITIONER NAME]`, `[NAME]` | Person names, classified by nearby label text (e.g. a table row labelled "Behaviour Support Practitioner") - falls back to a generic `[NAME]` for names in narrative text with no nearby label |
| `[PROVIDER ORGANISATION NAME]` | Organisation/provider names (generic terms like "NDIS", "Medicare", "Centrelink" are exempted - see `app/roles.py::ORG_ALLOWLIST`) |
| `[DOB]` | Dates only when labelled "date of birth" / "DOB" / "born" - plan dates, review dates etc. are left alone |
| `[NDIS NUMBER]` | 9-digit NDIS participant number, near the words "NDIS"/"participant number" |
| `[MEDICARE NUMBER]` | Australian Medicare number (checksum-validated) |
| `[ADDRESS]` | Full AU street address (street + suburb + state + postcode) |
| `[PHONE]` / `[EMAIL]` | Phone numbers / email addresses |

This is a heuristic, NLP-assisted process, not a guarantee - see
**Limitations** below. Always spot-check output before relying on it.

## Project layout

```
app/
  recognizers.py     - builds the presidio AnalyzerEngine (custom NDIS number
                        + AU address recognizers, AU_MEDICARE re-enabled,
                        ORGANIZATION re-enabled)
  roles.py            - maps a raw entity + nearby label text -> placeholder tag
  docx_processor.py   - walks the .docx (paragraphs, tables incl. nested,
                        headers/footers), redacts in place, preserves formatting
  deidentify.py       - top-level API used by the GUI and tests
  gui.py               - Tkinter + drag-and-drop desktop UI
main.py                - PyInstaller entry point
packaging/
  presidio_deid.spec   - PyInstaller build spec (onedir; produces .app on macOS)
tests/
  make_sample.py       - generates a synthetic NDIS-plan-shaped .docx fixture
  test_deidentify.py   - asserts planted PII is gone and placeholders are present
.github/workflows/
  build-desktop-app.yml - CI: builds Windows + macOS artifacts on tag push
```

## Running from source

```bash
python -m venv venv
# Windows:
venv\Scripts\pip install -r requirements.txt
venv\Scripts\python -m spacy download en_core_web_lg
venv\Scripts\python main.py
# macOS/Linux:
venv/bin/pip install -r requirements.txt
venv/bin/python -m spacy download en_core_web_lg
venv/bin/python main.py
```

Run the tests with:

```bash
pip install -r requirements-dev.txt
python -m pytest tests/ -v
```

## Building the desktop app

The spaCy model alone is several hundred MB, so the build uses PyInstaller's
**onedir** mode (a folder, not a single .exe) - a onefile build would have to
re-extract that on every launch.

```bash
pip install -r requirements.txt
python -m spacy download en_core_web_lg
pyinstaller packaging/presidio_deid.spec --noconfirm --distpath dist --workpath pybuild
```

- **Windows**: produces `dist/NDIS-Deidentifier/NDIS-Deidentifier.exe` plus
  its supporting files. Zip the whole `dist/NDIS-Deidentifier` folder to
  distribute it; users unzip and run the `.exe` inside - no Python install
  needed.
- **macOS**: the same command additionally produces
  `dist/NDIS-Deidentifier.app` (PyInstaller's `BUNDLE` step is a no-op on
  Windows/Linux, so this only appears when built *on* macOS). Zip the `.app`
  or wrap it in a `.dmg` to distribute.

**PyInstaller does not cross-compile** - a `.app` can only be built by running
PyInstaller on an actual Mac, and a `.exe` only on Windows. This repo is
being developed on Windows, so the Windows build was built and smoke-tested
locally; the macOS build has to come from either a Mac or CI.

### Getting the macOS build via CI

`.github/workflows/build-desktop-app.yml` builds both platforms and uploads
them as downloadable artifacts. To use it:

1. `git init` this repo (or push it into an existing GitHub repo) and push to GitHub.
2. Push a tag (`git tag v1.0.0 && git push --tags`) or trigger it manually
   from the Actions tab ("Run workflow").
3. Download the `NDIS-Deidentifier-macos` and `NDIS-Deidentifier-windows`
   artifacts from the completed workflow run.

## Design notes / limitations

- **Formatting compromise**: PII is detected on a paragraph's *merged* text
  (Word often splits one sentence across several runs), so when a paragraph
  contains a match, the whole paragraph's text is rewritten into its first
  run and the other runs are cleared. This keeps headings, table structure
  and paragraph-level styling intact; the only cosmetic loss is if a single
  paragraph mixed two different run-level formats (e.g. a bold label and a
  plain value on the same line) - the whole line then takes on the first
  run's formatting. NDIS templates almost always put label/value pairs in
  separate table cells or separate lines, so this rarely triggers.
- **Images/signatures**: this only redacts text. A scanned or inserted
  signature *image*, or a photo of the participant, is not touched.
- **Detection is probabilistic**: presidio combines regex/checksum
  recognizers with spaCy NER for names/organisations. NER can miss unusual
  names or flag false positives. Review the output before relying on it,
  especially for a document type as sensitive as a behaviour support plan.
- **Generic dates are left alone on purpose**: only dates near "date of
  birth"/"DOB"/"born" are redacted, so plan dates and review dates - which
  are operationally useful and not identifying on their own - survive.
- **Hyperlink target URLs** (e.g. a `mailto:` link's underlying address, as
  opposed to its displayed text) aren't rewritten, only the visible text is.
