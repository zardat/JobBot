import os
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from modules.sheets import get_credentials
from dotenv import load_dotenv

load_dotenv()

FOLDER_ID = os.getenv("GOOGLE_DRIVE_FOLDER_ID")


def get_drive_service():
    return build("drive", "v3", credentials=get_credentials())


def upload_resume(pdf_path, job_id):
    service = get_drive_service()
    file_name = f"resume_{job_id}.pdf"

    file_metadata = {
        "name": file_name,
        "parents": [FOLDER_ID],
    }
    media = MediaFileUpload(pdf_path, mimetype="application/pdf")

    uploaded = service.files().create(
        body=file_metadata,
        media_body=media,
        fields="id",
    ).execute()

    file_id = uploaded["id"]

    service.permissions().create(
        fileId=file_id,
        body={"type": "anyone", "role": "reader"},
    ).execute()

    shareable_link = f"https://drive.google.com/file/d/{file_id}/view"
    print(f"[drive] Uploaded {file_name} → {shareable_link}")
    return shareable_link
