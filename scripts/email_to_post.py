#!/usr/bin/env python3
"""
Email to Jekyll Post Converter
Connects to Gmail via IMAP, fetches unread emails, and creates Jekyll posts
"""

import imaplib
import email
from email.header import decode_header
import os
import re
from datetime import datetime
import html2text
import sys

# Configuration from environment variables
GMAIL_USER = os.environ.get('GMAIL_USER')
GMAIL_APP_PASSWORD = os.environ.get('GMAIL_APP_PASSWORD')
IMAP_SERVER = 'imap.gmail.com'
IMAP_PORT = 993

# Posts directory
POSTS_DIR = '_posts'


def sanitize_filename(text):
    """Convert text to a safe filename"""
    # Remove special characters and replace spaces with hyphens
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


def extract_email_body(msg):
    """Extract the body content from an email message"""
    body = ""

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition"))

            # Skip attachments
            if "attachment" in content_disposition:
                continue

            # Get the email body
            if content_type == "text/plain":
                try:
                    body = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                    break
                except:
                    pass
            elif content_type == "text/html" and not body:
                try:
                    html_body = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                    # Convert HTML to Markdown
                    h = html2text.HTML2Text()
                    h.ignore_links = False
                    h.ignore_images = False
                    h.ignore_emphasis = False
                    body = h.handle(html_body)
                except:
                    pass
    else:
        # Not multipart - get the payload directly
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


def create_jekyll_post(subject, body, date):
    """Create a Jekyll post from email content"""
    # Create filename
    date_str = date.strftime('%Y-%m-%d')
    title_slug = sanitize_filename(subject)
    filename = f"{date_str}-{title_slug}.md"
    filepath = os.path.join(POSTS_DIR, filename)

    # Check if file already exists
    if os.path.exists(filepath):
        print(f"Post already exists: {filename}")
        return False

    # Clean up body content
    body = body.strip()

    # Create post content with YAML front matter
    post_content = f"""---
layout: post
title: "{subject}"
date: {date.strftime('%Y-%m-%d %H:%M:%S %z')}
---

{body}
"""

    # Write the file
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(post_content)

    print(f"Created post: {filename}")
    return True


def process_emails():
    """Connect to Gmail and process unread emails"""
    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        print("Error: GMAIL_USER and GMAIL_APP_PASSWORD environment variables must be set")
        sys.exit(1)

    # Ensure posts directory exists
    os.makedirs(POSTS_DIR, exist_ok=True)

    try:
        # Connect to Gmail
        print(f"Connecting to {IMAP_SERVER}...")
        mail = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
        mail.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        print("Connected successfully!")

        # Select the inbox
        mail.select('INBOX')

        # Search for unread emails
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

        # Process each email
        for email_id in email_ids:
            try:
                # Fetch the email
                status, msg_data = mail.fetch(email_id, '(RFC822)')

                if status != 'OK':
                    print(f"Error fetching email {email_id}")
                    continue

                # Parse the email
                raw_email = msg_data[0][1]
                msg = email.message_from_bytes(raw_email)

                # Get subject
                subject = decode_email_header(msg['Subject'])
                if not subject:
                    subject = "Untitled Note"

                # Get date
                date_str = msg['Date']
                try:
                    email_date = email.utils.parsedate_to_datetime(date_str)
                except:
                    email_date = datetime.now()

                # Get body
                body = extract_email_body(msg)

                if not body:
                    print(f"Skipping email with empty body: {subject}")
                    continue

                # Create the post
                if create_jekyll_post(subject, body, email_date):
                    posts_created += 1

                    # Mark as read
                    mail.store(email_id, '+FLAGS', '\\Seen')
                    print(f"Marked email as read: {subject}")

            except Exception as e:
                print(f"Error processing email {email_id}: {str(e)}")
                continue

        print(f"\nProcessing complete. Created {posts_created} new post(s).")

        # Close connection
        mail.close()
        mail.logout()

    except Exception as e:
        print(f"Error: {str(e)}")
        sys.exit(1)


if __name__ == '__main__':
    process_emails()
