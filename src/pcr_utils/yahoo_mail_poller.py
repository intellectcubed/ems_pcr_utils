"""
Yahoo Mail Poller - Monitor Yahoo Mail for fax attachments and save them for processing
"""

import os
import imaplib
import email
import time
import signal
import logging
from pathlib import Path
from typing import Optional, List, Dict
from datetime import datetime
from email.header import decode_header
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class YahooMailPoller:
    """
    Polling service that monitors Yahoo Mail for fax notification emails
    and downloads PDF attachments to a watch directory.
    """

    # Yahoo Mail IMAP configuration
    IMAP_SERVER = 'imap.mail.yahoo.com'
    IMAP_PORT = 993

    # Email filter criteria
    TARGET_SUBJECT = '1 page fax received from VSI-FAX'
    TARGET_SENDER = 'SC911@mailfax.comm.somerset.nj.us'

    # State file configuration
    STATE_DIR = Path.home() / '.pcr_utils'
    STATE_FILE = 'processed_emails.txt'

    # Maximum emails to retrieve per polling cycle
    MAX_EMAILS_PER_POLL = 15

    def __init__(
        self,
        email_address: Optional[str] = None,
        password: Optional[str] = None,
        save_dir: Optional[str] = None,
        poll_interval: Optional[int] = None,
        day_poll_interval: Optional[int] = None,
        night_poll_interval: Optional[int] = None,
        night_start_hour: Optional[int] = None,
        night_end_hour: Optional[int] = None
    ):
        """
        Initialize the Yahoo Mail polling service.

        Args:
            email_address: Yahoo email address. If None, reads from YAHOO_EMAIL env variable
            password: Yahoo app password. If None, reads from YAHOO_PASSWORD env variable
            save_dir: Directory to save attachments. If None, reads from EMAIL_SAVE_DIR or WATCH_DIR env variable
            poll_interval: Legacy poll interval (deprecated, use day_poll_interval instead)
            day_poll_interval: Seconds between polls during daytime. If None, reads from DAY_POLL_INTERVAL_SECONDS env variable (default: 900 = 15 min)
            night_poll_interval: Seconds between polls during nighttime. If None, reads from NIGHT_POLL_INTERVAL_SECONDS env variable (default: 3600 = 1 hour)
            night_start_hour: Hour when nighttime begins (0-23). If None, reads from NIGHT_START_HOUR env variable (default: 23 = 11pm)
            night_end_hour: Hour when nighttime ends (0-23). If None, reads from NIGHT_END_HOUR env variable (default: 6 = 6am)

        Raises:
            ValueError: If credentials or save directory are not configured
        """
        # Get credentials from parameters or environment
        self.email_address = email_address or os.getenv('YAHOO_EMAIL')
        self.password = password or os.getenv('YAHOO_PASSWORD')

        if not self.email_address or not self.password:
            raise ValueError(
                "Yahoo Mail credentials not configured. Provide via parameters or "
                "set YAHOO_EMAIL and YAHOO_PASSWORD environment variables.\n"
                "Note: Yahoo Mail requires an app-specific password. Generate one at:\n"
                "https://login.yahoo.com/account/security/app-passwords"
            )

        # Get save directory
        save_dir_path = save_dir or os.getenv('EMAIL_SAVE_DIR') or os.getenv('WATCH_DIR')
        if not save_dir_path:
            raise ValueError(
                "Save directory not configured. Provide via save_dir parameter or "
                "set EMAIL_SAVE_DIR or WATCH_DIR environment variable"
            )

        self.save_dir = Path(save_dir_path)
        if not self.save_dir.exists():
            raise ValueError(f"Save directory does not exist: {self.save_dir}")

        if not self.save_dir.is_dir():
            raise ValueError(f"Save directory is not a directory: {self.save_dir}")

        # Get time-based poll intervals
        # Support legacy EMAIL_POLL_INTERVAL_SECONDS for backwards compatibility
        legacy_interval = poll_interval or int(os.getenv('EMAIL_POLL_INTERVAL_SECONDS', '900'))

        self.day_poll_interval = day_poll_interval or int(os.getenv('DAY_POLL_INTERVAL_SECONDS', str(legacy_interval)))
        self.night_poll_interval = night_poll_interval or int(os.getenv('NIGHT_POLL_INTERVAL_SECONDS', '3600'))
        self.night_start_hour = night_start_hour if night_start_hour is not None else int(os.getenv('NIGHT_START_HOUR', '23'))
        self.night_end_hour = night_end_hour if night_end_hour is not None else int(os.getenv('NIGHT_END_HOUR', '6'))

        # Setup state file path
        self.STATE_DIR.mkdir(parents=True, exist_ok=True)
        self.state_file_path = self.STATE_DIR / self.STATE_FILE

        # Load processed email IDs
        self.processed_message_ids = self._load_processed_ids()

        # IMAP connection (will be established in run loop)
        self.imap = None

        # Flag for graceful shutdown
        self.running = False

        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        logger.info("Yahoo Mail Poller initialized")
        logger.info(f"  Email: {self.email_address}")
        logger.info(f"  Save directory: {self.save_dir}")
        logger.info(f"  Day poll interval: {self.day_poll_interval} seconds ({self.day_poll_interval // 60} min)")
        logger.info(f"  Night poll interval: {self.night_poll_interval} seconds ({self.night_poll_interval // 60} min)")
        logger.info(f"  Night hours: {self.night_start_hour}:00 - {self.night_end_hour}:00")
        logger.info(f"  State file: {self.state_file_path}")

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully."""
        logger.info(f"Received signal {signum}, shutting down gracefully...")
        self.running = False

    def _get_poll_interval(self) -> int:
        """
        Calculate poll interval based on time of day.

        Returns:
            Poll interval in seconds (day_poll_interval for daytime, night_poll_interval for nighttime)
        """
        current_hour = datetime.now().hour

        # Check if current time is in night hours
        # Handle case where night spans midnight (e.g., 23:00 to 6:00)
        if self.night_start_hour > self.night_end_hour:
            # Night spans midnight (e.g., 23 to 6)
            is_night = current_hour >= self.night_start_hour or current_hour < self.night_end_hour
        else:
            # Night doesn't span midnight (e.g., 1 to 5)
            is_night = self.night_start_hour <= current_hour < self.night_end_hour

        if is_night:
            logger.debug(f"Night mode: using {self.night_poll_interval}s interval")
            return self.night_poll_interval
        else:
            logger.debug(f"Day mode: using {self.day_poll_interval}s interval")
            return self.day_poll_interval

    def _load_processed_ids(self) -> set:
        """
        Load processed Message-IDs from text file.

        Returns:
            Set of processed Message-IDs
        """
        if not self.state_file_path.exists():
            logger.info("No state file found, starting fresh")
            return set()

        try:
            with open(self.state_file_path, 'r') as f:
                # Read all lines, strip whitespace, filter empty lines
                message_ids = {line.strip() for line in f if line.strip()}
                logger.info(f"Loaded {len(message_ids)} processed email Message-IDs")
                return message_ids
        except Exception as e:
            logger.error(f"Failed to load state file: {e}, starting fresh")
            return set()

    def _add_processed_id(self, message_id: str):
        """
        Add a Message-ID to the processed list and save to file.

        Args:
            message_id: Email Message-ID to mark as processed
        """
        try:
            # Add to in-memory set
            self.processed_message_ids.add(message_id)

            # Append to file
            with open(self.state_file_path, 'a') as f:
                f.write(f"{message_id}\n")

            logger.debug(f"Marked as processed: {message_id}")
        except Exception as e:
            logger.error(f"Failed to save processed Message-ID: {e}")

    def _connect_imap(self) -> bool:
        """
        Connect to Yahoo Mail IMAP server.

        Returns:
            True if connection successful, False otherwise
        """
        try:
            # Create IMAP4 SSL connection
            self.imap = imaplib.IMAP4_SSL(self.IMAP_SERVER, self.IMAP_PORT)

            # Login
            self.imap.login(self.email_address, self.password)

            # Select inbox
            status, messages = self.imap.select('INBOX')
            if status != 'OK':
                logger.error(f"Failed to select INBOX: {status}")
                return False

            logger.info("Successfully connected to Yahoo Mail")
            return True

        except imaplib.IMAP4.error as e:
            logger.error(f"IMAP error: {e}")
            logger.error("Make sure you're using an app-specific password from Yahoo")
            return False
        except Exception as e:
            logger.error(f"Failed to connect to Yahoo Mail: {e}")
            return False

    def _disconnect_imap(self):
        """Disconnect from IMAP server."""
        if self.imap:
            try:
                self.imap.close()
                self.imap.logout()
                logger.debug("Disconnected from Yahoo Mail")
            except Exception as e:
                logger.error(f"Error disconnecting from IMAP: {e}")

    def _decode_mime_header(self, header_value: str) -> str:
        """
        Decode MIME encoded header.

        Args:
            header_value: Header value to decode

        Returns:
            Decoded string
        """
        if not header_value:
            return ""

        decoded_parts = decode_header(header_value)
        result = []

        for content, encoding in decoded_parts:
            if isinstance(content, bytes):
                result.append(content.decode(encoding or 'utf-8', errors='ignore'))
            else:
                result.append(content)

        return ' '.join(result)

    def _search_emails(self) -> List[str]:
        """
        Search for READ emails matching our criteria.
        Returns up to MAX_EMAILS_PER_POLL most recent emails.

        Returns:
            List of email UIDs (newest first, up to 15)
        """
        try:
            # Search for SEEN (read) emails from the target sender
            # Yahoo IMAP supports searching by FROM
            search_criteria = f'(SEEN FROM "{self.TARGET_SENDER}")'
            status, messages = self.imap.search(None, search_criteria)

            if status != 'OK':
                logger.error(f"Email search failed: {status}")
                return []

            # Get list of email UIDs
            email_uids = messages[0].split()

            if not email_uids:
                logger.debug("No emails found matching sender criteria")
                return []

            # Reverse to get newest first, then limit to MAX_EMAILS_PER_POLL
            email_uids.reverse()
            email_uids = email_uids[:self.MAX_EMAILS_PER_POLL]

            # Convert bytes to strings
            email_uids = [uid.decode() if isinstance(uid, bytes) else uid
                         for uid in email_uids]

            logger.info(f"Found {len(email_uids)} recent emails to check")
            return email_uids

        except Exception as e:
            logger.error(f"Error searching emails: {e}")
            return []

    def _check_subject_match(self, subject: str) -> bool:
        """
        Check if email subject matches our target.

        Args:
            subject: Email subject to check

        Returns:
            True if subject contains target text
        """
        return self.TARGET_SUBJECT.lower() in subject.lower()

    def _process_email(self, email_uid: str) -> Optional[str]:
        """
        Process a single email: check if already processed, download attachments if new.

        Args:
            email_uid: Email UID to process

        Returns:
            Message-ID if this is a new email that was processed, None if already processed
        """
        try:
            # Fetch email using BODY.PEEK[] to avoid setting \Seen flag
            # This ensures we don't interfere with other email processing services
            status, msg_data = self.imap.fetch(email_uid, '(BODY.PEEK[])')
            if status != 'OK':
                logger.error(f"Failed to fetch email {email_uid}")
                return None

            # Parse email
            email_body = msg_data[0][1]
            message = email.message_from_bytes(email_body)

            # Get Message-ID
            message_id = message.get('Message-ID', '').strip()
            if not message_id:
                logger.warning(f"Email {email_uid} has no Message-ID, skipping")
                return None

            # Check if already processed
            if message_id in self.processed_message_ids:
                logger.info(f"Email already processed (stopping): {message_id}")
                return None

            # Check subject
            subject = self._decode_mime_header(message.get('Subject', ''))
            if not self._check_subject_match(subject):
                logger.debug(f"Email {email_uid} subject doesn't match: {subject}")
                # Mark as processed even if subject doesn't match, so we don't check it again
                self._add_processed_id(message_id)
                return None

            # Get sender
            sender = self._decode_mime_header(message.get('From', ''))
            logger.info(f"Processing email from {sender}: {subject}")

            # Process attachments
            attachment_count = 0

            for part in message.walk():
                # Skip multipart containers
                if part.get_content_maintype() == 'multipart':
                    continue

                # Log part info for debugging
                content_type = part.get_content_type()
                content_disp = part.get('Content-Disposition')
                logger.debug(f"  Part: {content_type}, Disposition: {content_disp}")

                # Check if this is an attachment or inline PDF
                # Fax emails often send PDFs as application/octet-stream without Content-Disposition
                is_attachment = content_disp and ('attachment' in content_disp.lower() or 'inline' in content_disp.lower())
                is_pdf_type = content_type == 'application/pdf'
                is_octet_stream = content_type == 'application/octet-stream'

                # Skip text/plain and other obvious non-attachments
                if content_type in ['text/plain', 'text/html', 'multipart/alternative', 'multipart/mixed']:
                    continue

                # Process if it's an attachment, a PDF, or an octet-stream (likely a PDF)
                if not (is_attachment or is_pdf_type or is_octet_stream):
                    continue

                # Get filename
                filename = part.get_filename()
                if not filename:
                    # For inline PDFs/octet-streams without filename, generate one
                    if is_pdf_type or is_octet_stream:
                        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
                        filename = f"fax_{email_uid}_{timestamp}.pdf"
                        logger.info(f"  No filename, generated: {filename}")
                    else:
                        continue

                filename = self._decode_mime_header(filename)

                # For octet-stream, accept any file (likely PDF from fax system)
                # For other types, only save PDF files
                if not is_octet_stream and not filename.lower().endswith('.pdf'):
                    logger.info(f"  Skipping non-PDF: {filename}")
                    continue

                # If octet-stream doesn't have .pdf extension, add it
                if is_octet_stream and not filename.lower().endswith('.pdf'):
                    filename = f"{filename}.pdf"
                    logger.info(f"  Added .pdf extension: {filename}")

                # Get attachment data
                attachment_data = part.get_payload(decode=True)
                if not attachment_data:
                    logger.warning(f"Empty attachment: {filename}")
                    continue

                # Save to watch directory
                save_path = self.save_dir / filename

                # Handle duplicate filenames
                if save_path.exists():
                    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                    name_parts = filename.rsplit('.', 1)
                    filename = f"{name_parts[0]}_{timestamp}.{name_parts[1]}"
                    save_path = self.save_dir / filename
                    logger.info(f"  File exists, using new name: {filename}")

                # Write file
                with open(save_path, 'wb') as f:
                    f.write(attachment_data)

                logger.info(f"  Saved attachment: {filename} ({len(attachment_data)} bytes)")
                attachment_count += 1

            # Mark email as processed
            self._add_processed_id(message_id)

            if attachment_count > 0:
                logger.info(f"  Downloaded {attachment_count} attachment(s) from {message_id}")
                return message_id
            else:
                logger.info(f"  No attachments found in {message_id}")
                return message_id

        except Exception as e:
            logger.error(f"Error processing email {email_uid}: {e}")
            return None

    def _process_new_emails(self) -> Dict[str, int]:
        """
        Process new emails: search up to 15 most recent, process newest first,
        stop at first already-processed email.

        Returns:
            Dictionary with processing statistics
        """
        stats = {
            "emails_checked": 0,
            "emails_processed": 0
        }

        # Search for up to 15 most recent emails
        email_uids = self._search_emails()

        if not email_uids:
            logger.debug("No emails to check")
            return stats

        # Process each email (newest first), stop at first already-processed
        for email_uid in email_uids:
            stats["emails_checked"] += 1

            # Process email - returns Message-ID if new, None if already processed
            message_id = self._process_email(email_uid)

            if message_id is None:
                # Already processed - stop checking older emails
                logger.info("Encountered already-processed email, stopping")
                break
            else:
                # New email was processed
                stats["emails_processed"] += 1

        if stats["emails_processed"] > 0:
            logger.info(f"Processed {stats['emails_processed']} new email(s)")

        return stats

    def run(self):
        """
        Start the polling service. Runs until interrupted (Ctrl+C or SIGTERM).
        """
        self.running = True
        logger.info("Yahoo Mail Poller started. Press Ctrl+C to stop.")

        while self.running:
            try:
                # Connect to IMAP
                if not self._connect_imap():
                    logger.error("Failed to connect to Yahoo Mail, will retry on next poll")
                    if self.running:
                        poll_interval = self._get_poll_interval()
                        time.sleep(poll_interval)
                    continue

                # Process emails
                stats = self._process_new_emails()

                if stats["emails_checked"] > 0:
                    logger.info(
                        f"Checked {stats['emails_checked']} email(s), "
                        f"processed {stats['emails_processed']} new email(s)"
                    )

                # Disconnect
                self._disconnect_imap()

                # Sleep until next poll (dynamic based on time of day)
                if self.running:
                    poll_interval = self._get_poll_interval()
                    logger.info(f"Sleeping for {poll_interval} seconds ({poll_interval // 60} min)")
                    time.sleep(poll_interval)

            except Exception as e:
                logger.error(f"Unexpected error in polling loop: {e}", exc_info=True)
                # Ensure disconnection
                self._disconnect_imap()
                # Continue running despite errors
                if self.running:
                    poll_interval = self._get_poll_interval()
                    time.sleep(poll_interval)

        logger.info("Yahoo Mail Poller stopped.")


if __name__ == "__main__":
    import argparse

    # Set up argument parser
    parser_args = argparse.ArgumentParser(
        description='Yahoo Mail Poller - Monitor Yahoo Mail for fax attachments'
    )
    parser_args.add_argument(
        '--email',
        default=None,
        help='Yahoo email address (default: from YAHOO_EMAIL env variable)'
    )
    parser_args.add_argument(
        '--password',
        default=None,
        help='Yahoo app password (default: from YAHOO_PASSWORD env variable)'
    )
    parser_args.add_argument(
        '--save-dir',
        default=None,
        help='Directory to save attachments (default: from EMAIL_SAVE_DIR or WATCH_DIR env variable)'
    )
    parser_args.add_argument(
        '--poll-interval',
        type=int,
        default=None,
        help='Seconds between polls (default: from EMAIL_POLL_INTERVAL_SECONDS env variable, or 300)'
    )

    args = parser_args.parse_args()

    try:
        # Create and start the polling service
        poller = YahooMailPoller(
            email_address=args.email,
            password=args.password,
            save_dir=args.save_dir,
            poll_interval=args.poll_interval
        )
        poller.run()

    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        exit(1)
    except KeyboardInterrupt:
        logger.info("Service stopped by user")
        exit(0)
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        exit(1)
