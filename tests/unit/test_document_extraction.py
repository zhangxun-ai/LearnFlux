from pypdf import PdfWriter


def test_pdf_extractor_opens_aes256_document_with_empty_user_password(tmp_path):
    from video_transcript_api.api.services.transcription import _extract_document_text

    pdf_path = tmp_path / "encrypted.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.encrypt(user_password="", owner_password="owner", algorithm="AES-256")
    with pdf_path.open("wb") as output:
        writer.write(output)

    assert _extract_document_text(str(pdf_path), ".pdf") == ""
