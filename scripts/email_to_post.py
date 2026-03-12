#!/usr/bin/env python3
"""
Email to Jekyll Post Converter
Connects to Gmail via IMAP, fetches unread emails, and creates Jekyll posts.
Uses Gemini AI for auto-tagging and link summarization.
"""

import imaplib
import email
import email.utils
from email.header import decode_header
import os
import re
import json
from datetime import datetime
import html2text
import sys
import trafilatura
from google import genai

# Configuration from environment variables
GMAIL_USER = os.environ.get('GMAIL_USER')
GMAIL_APP_PASSWORD = os.environ.get('GMAIL_APP_PASSWORD')
ALLOWED_SENDERS = os.environ.get('ALLOWED_SENDERS', '').split(',')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
IMAP_SERVER = 'imap.gmail.com'
IMAP_PORT = 993

POSTS_DIR = '_posts'
TAGS_DIR = 'tags'


def sanitize_filename(text):
    """Convert text to a safe filename"""
    text = re.sub(r'[^\w\s-]', '', text.lower())
    text = re.sub(r'[-\s]+', '-', text)
    return text.strip('-')


def decode_email_header(header):
    """Decode email header to string"""
    if header is None:
        return ''

    decoded = decode_header(header)
    header_parts = []

    for content, charset in decoded:
        if isinstance(content, bytes):
            try:
                if charset:
                    header_parts.append(content.decode(charset))
                else:
                    header_parts.append(content.decode('utf-8'))
            except:
                header_parts.append(content.decode('utf-8', errors='ignore'))
        else:
            header_parts.append(content)

    return ''.join(header_parts)


def autolink_urls(text):
    """Convert bare URLs to Markdown links, skipping ones already in link syntax."""
    pattern = r'(?<!\()(?<!\[)(https?://[^\s\)<>\[\]]+)'
    return re.sub(pattern, r'[\1](\1)', text)


def extract_email_body(msg):
    """Extract the body content from an email message"""
    body = ""

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition"))

            if "attachment" in content_disposition:
                continue

            if content_type == "text/plain":
                try:
                    body = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                    break
                except:
                    pass
            elif content_type == "text/html" and not body:
                try:
                    html_body = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                    h = html2text.HTML2Text()
                    h.ignore_links = False
                    h.ignore_images = False
                    h.ignore_emphasis = False
                    body = h.handle(html_body)
                except:
                    pass
    else:
        content_type = msg.get_content_type()
        try:
            if content_type == "text/plain":
                body = msg.get_payload(decode=True).decode('utf-8', errors='ignore')
            elif content_type == "text/html":
                html_body = msg.get_payload(decode=True).decode('utf-8', errors='ignore')
                h = html2text.HTML2Text()
                h.ignore_links = False
                h.ignore_images = False
                h.ignore_emphasis = False
                body = h.handle(html_body)
        except:
            body = ""

    return body.strip()


def fetch_page_text(url):
    """Fetch and extract readable text from a URL using trafilatura."""
    try:
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return None
        text = trafilatura.extract(downloaded, include_comments=False, include_tables=False)
        if text:
            # Truncate to avoid huge prompts
            return text[:3000]
        return None
    except Exception as e:
        print(f"Could not fetch page content from {url}: {e}")
        return None


def enhance_with_ai(subject, body_text, fetch_url=None):
    """
    Use Gemini to generate tags and (for link posts) a short summary.
    Returns (tags_list, summary_str). Both are empty/None on failure.
    """
    if not GEMINI_API_KEY:
        print("GEMINI_API_KEY not set — skipping AI enhancement")
        return [], None

    try:
        client = genai.Client(api_key=GEMINI_API_KEY)

        page_content = None
        if fetch_url:
            print(f"Fetching page content from {fetch_url}...")
            page_content = fetch_page_text(fetch_url)

        if page_content:
            prompt = f"""You're helping catalog bookmarks for a casual personal tech/notes site.

Post title: {subject}
Article content (truncated):
{page_content}

Respond ONLY with valid JSON, no other text:
{{
  "tags": ["tag1", "tag2"],
  "summary": "2-3 sentences in a casual, direct voice. Skip phrases like 'the article discusses' or 'this post covers'. Just say what it is and why it's interesting."
}}

Rules for tags: 2-4 tags, lowercase, hyphenated if multi-word (e.g. "machine-learning", "open-source"). Pick the most specific relevant categories."""
        else:
            prompt = f"""You're helping catalog notes for a casual personal tech/notes site.

Post title: {subject}
Post content: {body_text[:1000] if body_text else '(no body)'}

Respond ONLY with valid JSON, no other text:
{{
  "tags": ["tag1", "tag2"]
}}

Rules for tags: 2-4 tags, lowercase, hyphenated if multi-word (e.g. "machine-learning", "open-source"). Pick the most specific relevant categories."""

        response = client.models.generate_content(
            model='gemini-1.5-flash',
            contents=prompt
        )
        raw = response.text.strip()

        # Strip markdown code fences if present
        raw = re.sub(r'^```(?:json)?\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw)

        data = json.loads(raw)
        tags = [str(t).lower().strip() for t in data.get('tags', [])]
        summary = data.get('summary', None)
        print(f"AI tags: {tags}")
        if summary:
            print(f"AI summary: {summary[:80]}...")
        return tags, summary

    except Exception as e:
        print(f"AI enhancement failed: {e}")
        return [], None


def ensure_tag_pages(tags):
    """Create a stub tag page for any tag that doesn't have one yet."""
    os.makedirs(TAGS_DIR, exist_ok=True)
    for tag in tags:
        tag_slug = sanitize_filename(tag)
        tag_dir = os.path.join(TAGS_DIR, tag_slug)
        tag_file = os.path.join(tag_dir, 'index.html')
        if not os.path.exists(tag_file):
            os.makedirs(tag_dir, exist_ok=True)
            content = f"""---
layout: tag_page
tag: {tag}
title: "Posts tagged: {tag}"
permalink: /tags/{tag_slug}/
---
"""
            with open(tag_file, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"Created tag page: /tags/{tag_slug}/")


def create_jekyll_post(subject, body, date, tags=None, ai_summary=None):
    """Create a Jekyll post from email content"""
    date_str = date.strftime('%Y-%m-%d')
    title_slug = sanitize_filename(subject)
    filename = f"{date_str}-{title_slug}.md"
    filepath = os.path.join(POSTS_DIR, filename)

    if os.path.exists(filepath):
        print(f"Post already exists: {filename}")
        return False

    # Build YAML front matter
    tags_yaml = ''
    if tags:
        tag_list = ', '.join(f'"{t}"' for t in tags)
        tags_yaml = f'\ntags: [{tag_list}]'

    # Append AI summary below the body if present
    full_body = body.strip()
    if ai_summary:
        full_body += f'\n\n*{ai_summary.strip()}*'

    post_content = f"""---
layout: post
title: "{subject}"{tags_yaml}
date: {date.strftime('%Y-%m-%d %H:%M:%S %z')}
---

{full_body}
"""

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(post_content)

    print(f"Created post: {filename}")

    if tags:
        ensure_tag_pages(tags)

    return True


def process_emails():
    """Connect to Gmail and process unread emails"""
    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        print("Error: GMAIL_USER and GMAIL_APP_PASSWORD environment variables must be set")
        sys.exit(1)

    if not ALLOWED_SENDERS or ALLOWED_SENDERS == ['']:
        print("Error: ALLOWED_SENDERS environment variable must be set")
        sys.exit(1)

    allowed_senders = [sender.strip().lower() for sender in ALLOWED_SENDERS if sender.strip()]
    print(f"Allowed senders: {', '.join(allowed_senders)}")

    os.makedirs(POSTS_DIR, exist_ok=True)

    try:
        print(f"Connecting to {IMAP_SERVER}...")
        mail = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
        mail.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        print("Connected successfully!")

        mail.select('INBOX')
        status, messages = mail.search(None, 'UNSEEN')

        if status != 'OK':
            print("Error searching for emails")
            return

        email_ids = messages[0].split()

        if not email_ids:
            print("No unread emails found")
            return

        print(f"Found {len(email_ids)} unread email(s)")
        posts_created = 0

        for email_id in email_ids:
            try:
                status, msg_data = mail.fetch(email_id, '(RFC822)')

                if status != 'OK':
                    print(f"Error fetching email {email_id}")
                    continue

                raw_email = msg_data[0][1]
                msg = email.message_from_bytes(raw_email)

                # Check sender
                from_header = decode_email_header(msg['From'])
                from_match = re.search(r'<(.+?)>', from_header)
                sender_email = from_match.group(1).lower() if from_match else from_header.lower()

                if sender_email not in allowed_senders:
                    print(f"Skipping email from unauthorized sender: {sender_email}")
                    mail.store(email_id, '+FLAGS', '\\Seen')
                    continue

                print(f"Processing email from authorized sender: {sender_email}")

                subject = decode_email_header(msg['Subject'])
                if not subject:
                    subject = "Untitled Note"

                date_str = msg['Date']
                try:
                    email_date = email.utils.parsedate_to_datetime(date_str)
                except:
                    email_date = datetime.now()

                # Extract body (raw, no autolink yet)
                body = extract_email_body(msg)

                if not body:
                    print(f"Skipping email with empty body: {subject}")
                    continue

                # Feature 1: Detect single-URL body → use subject as link text
                body_raw = body.strip()
                fetch_url = None

                if re.match(r'^https?://\S+$', body_raw):
                    fetch_url = body_raw
                    body = f'[{subject}]({fetch_url})'
                else:
                    body = autolink_urls(body)
                    url_match = re.search(r'https?://[^\s\)<>\[\]]+', body_raw)
                    if url_match:
                        fetch_url = url_match.group(0).rstrip('.,;:)')

                # Features 2+3: AI tagging and summarization
                tags, ai_summary = enhance_with_ai(subject, body_raw, fetch_url)

                if create_jekyll_post(subject, body, email_date, tags=tags, ai_summary=ai_summary):
                    posts_created += 1
                    mail.store(email_id, '+FLAGS', '\\Seen')
                    print(f"Marked email as read: {subject}")

            except Exception as e:
                print(f"Error processing email {email_id}: {str(e)}")
                continue

        print(f"\nProcessing complete. Created {posts_created} new post(s).")

        mail.close()
        mail.logout()

    except imaplib.IMAP4.error as e:
        print(f"Gmail authentication failed: {str(e)}")
        print("Check that GMAIL_APP_PASSWORD is correct and not expired.")
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {type(e).__name__}: {str(e)}")
        sys.exit(1)


if __name__ == '__main__':
    process_emails()
