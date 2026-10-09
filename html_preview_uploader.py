"""Drag an HTML file onto this script to upload it to a Render preview session."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

# Change this to your Render service URL
RENDER_BASE_URL = "https://studentleadervote2026.onrender.com/"
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
CHUNK_SIZE = 500 * 1024  # 500 KB chunks


class PreviewSafetyChecker(HTMLParser):
    

    BLOCKED_TAGS = {"script", "form", "object", "embed", "base"}
    BLOCKED_ATTRS = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in self.BLOCKED_TAGS:
            raise ValueError(f"Blocked HTML element: <{tag}>")

        attributes = {name.lower(): (value or "") for name, value in attrs}
        if tag == "input" and attributes.get("type", "text").lower() == "password":
            raise ValueError("Password fields are not allowed in preview HTML")

        for name, value in attributes.items():
            if name.startswith("on") or name in self.BLOCKED_ATTRS:
                raise ValueError(f"Blocked HTML attribute: {name}")
            lowered = value.strip().lower()
            if lowered.startswith(("javascript:", "data:text/html")):
                raise ValueError(f"Blocked active URL in attribute: {name}")


def choose_file() -> Path:
    if len(sys.argv) > 1:
        return Path(sys.argv[1].strip('"')).expanduser().resolve()

    try:
        from tkinter import Tk, filedialog

        root = Tk()
        root.withdraw()
        selected = filedialog.askopenfilename(
            title="Select preview HTML",
            filetypes=[("HTML files", "*.html *.htm")],
        )
        root.destroy()
    except Exception:
        selected = ""

    if not selected:
        raise ValueError("No HTML file selected")
    return Path(selected).resolve()


def load_and_validate(path: Path) -> str:
    if path.suffix.lower() not in {".html", ".htm"}:
        raise ValueError("Only .html and .htm files are accepted")
    if not path.is_file():
        raise ValueError(f"File does not exist: {path}")
    if path.stat().st_size > MAX_FILE_SIZE:
        raise ValueError(f"HTML file is larger than {MAX_FILE_SIZE // (1024*1024)} MB")

    html = path.read_text(encoding="utf-8-sig")
    # Safety checker disabled for now
    # checker = PreviewSafetyChecker()
    # checker.feed(html)
    # checker.close()
    return html


def upload_chunked(session_id: str, filename: str, html: str) -> None:
    """Upload HTML in chunks to avoid payload size limits."""
    safe_session_id = urllib.parse.quote(session_id, safe="")
    base_url = f"{RENDER_BASE_URL.rstrip('/')}/api/session/{safe_session_id}"
    
    # Step 1: Initialize upload
    init_url = f"{base_url}/upload/init"
    init_data = json.dumps({
        "filename": filename, 
        "total_size": len(html),
        "chunk_size": CHUNK_SIZE
    }).encode("utf-8")
    
    init_req = urllib.request.Request(
        init_url,
        data=init_data,
        method="POST",
        headers={"Content-Type": "application/json"}
    )
    
    try:
        with urllib.request.urlopen(init_req, timeout=20) as response:
            result = json.loads(response.read().decode())
            upload_id = result.get("upload_id")
            if not upload_id:
                raise RuntimeError("Server didn't return upload_id")
            print(f"✓ Upload initialized: {upload_id}")
    except urllib.error.HTTPError as e:
        # If chunked upload isn't supported, fall back to direct upload
        if e.code == 404:
            print("  ⚠️ Server doesn't support chunked upload, trying direct upload...")
            upload_direct(session_id, filename, html)
            return
        raise RuntimeError(f"Failed to initialize upload: {e}")
    except Exception as e:
        raise RuntimeError(f"Failed to initialize upload: {e}")

    # Step 2: Upload chunks
    total_chunks = (len(html) + CHUNK_SIZE - 1) // CHUNK_SIZE
    
    for i in range(0, len(html), CHUNK_SIZE):
        chunk_num = i // CHUNK_SIZE + 1
        chunk = html[i:i+CHUNK_SIZE]
        
        chunk_url = f"{base_url}/upload/chunk"
        chunk_data = json.dumps({
            "upload_id": upload_id,
            "chunk_num": chunk_num,
            "total_chunks": total_chunks,
            "chunk": chunk
        }).encode("utf-8")
        
        chunk_req = urllib.request.Request(
            chunk_url,
            data=chunk_data,
            method="POST",
            headers={"Content-Type": "application/json"}
        )
        
        try:
            with urllib.request.urlopen(chunk_req, timeout=30) as response:
                progress = (chunk_num / total_chunks) * 100
                # Print progress on one line
                print(f"\r  Uploading: {chunk_num}/{total_chunks} chunks ({progress:.0f}%)", end="")
                sys.stdout.flush()
        except Exception as e:
            raise RuntimeError(f"Failed to upload chunk {chunk_num}: {e}")
    
    print()  # New line after progress
    
    # Step 3: Complete upload
    complete_url = f"{base_url}/upload/complete"
    complete_data = json.dumps({"upload_id": upload_id}).encode("utf-8")
    
    complete_req = urllib.request.Request(
        complete_url,
        data=complete_data,
        method="POST",
        headers={"Content-Type": "application/json"}
    )
    
    try:
        with urllib.request.urlopen(complete_req, timeout=20) as response:
            print("✓ Upload complete!")
    except Exception as e:
        raise RuntimeError(f"Failed to complete upload: {e}")


def upload_direct(session_id: str, filename: str, html: str) -> None:
    """Direct upload (fallback if chunked isn't supported)."""
    safe_session_id = urllib.parse.quote(session_id, safe="")
    url = f"{RENDER_BASE_URL.rstrip('/')}/api/session/{safe_session_id}/html"
    body = json.dumps({"filename": filename, "html": html}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "User-Agent": "HtmlUploader/1.0",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            response_text = response.read().decode("utf-8", errors="replace")
            if response.status not in {200, 201, 202, 204}:
                raise RuntimeError(f"Server returned HTTP {response.status}: {response_text}")
            print("✓ Upload successful!")
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Upload failed (HTTP {exc.code}): {details}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not connect to Render: {exc.reason}") from exc


def main() -> int:
    print("=" * 50)
    print("HTML Preview Uploader (Chunked)")
    print("=" * 50)
    
    try:
        # Get the HTML file
        path = choose_file()
        html = load_and_validate(path)
        file_size = len(html.encode('utf-8'))
        print(f"✓ File loaded: {path.name} ({file_size:,} bytes)")

        # Get session ID from user
        print("\n" + "-" * 50)
        print("📋 Copy the session ID from your waiting page URL")
        print("   Example: https://yoursite.com/?session=abc123xyz")
        print("-" * 50)
        session_id = input("Session ID: ").strip()
        
        if not session_id:
            raise ValueError("Session ID cannot be empty")

        # Upload
        print(f"\n📤 Uploading to session: {session_id}...")
        
        if file_size > 500 * 1024:  # If file > 500KB, use chunked upload
            upload_chunked(session_id, path.name, html)
        else:
            upload_direct(session_id, path.name, html)
        
        print(f"\n✅ Complete! The waiting page will now show your HTML.")
        print(f"   View it at: {RENDER_BASE_URL}?session={session_id}")
        
        return 0
        
    except (OSError, UnicodeError, ValueError, RuntimeError) as exc:
        print(f"\n❌ Error: {exc}")
        return 1
    finally:
        if sys.stdin.isatty():
            input("\nPress Enter to close...")


if __name__ == "__main__":
    raise SystemExit(main())