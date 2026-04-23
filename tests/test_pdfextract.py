import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

def test_import():
    import pdfextract
    assert hasattr(pdfextract, 'extract_pdf')

def test_pdf_parse_error():
    import pdfextract
    assert hasattr(pdfextract, 'PDFParseError')

def test_page_result():
    import pdfextract
    assert hasattr(pdfextract, 'PageResult')

def test_extraction_result():
    import pdfextract
    assert hasattr(pdfextract, 'ExtractionResult')
