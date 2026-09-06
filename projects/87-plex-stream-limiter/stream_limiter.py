import argparse
import sys
import time
import requests
import logging
import json
from typing import List, Dict, Any
from prometheus_client import start_http_server, Gauge

class JsonFormatter(logging.Formatter):
    def format(self, record):
        log_record = {
            "level": record.levelname,
            "message": record.getMessage(),
        }
        return json.dumps(log_record)

def setup_logging(json_format: bool):
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    if json_format:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    logger.addHandler(handler)
    return logger

class MetricsExporter:
    def __init__(self, port: int = 9116):
        self.port = port
        self.active_streams = Gauge('homelab_plex_active_streams_total', 'Total active Plex streams')
        self.transcodes = Gauge('homelab_plex_transcodes_total', 'Total active Plex transcodes')
        self.bandwidth_bps = Gauge('homelab_plex_bandwidth_bps_total', 'Total Plex bandwidth usage in bps')

    def start(self):
        start_http_server(self.port)
        logging.info(f"Started Prometheus exporter on port {self.port}")

    def update(self, sessions: List[Dict[str, Any]]):
        active_streams_count = len(sessions)
        transcode_count = sum(1 for s in sessions if s["is_transcoding"])
        total_bandwidth = sum(s["bitrate"] for s in sessions)

        self.active_streams.set(active_streams_count)
        self.transcodes.set(transcode_count)
        self.bandwidth_bps.set(total_bandwidth * 1000) # converting kbps to bps if bitrate is in kbps, usually Plex gives kbps

class PlexSessionAuditor:
    def __init__(self, plex_url: str, plex_token: str):
        self.plex_url = plex_url.rstrip("/")
        self.plex_token = plex_token

    def get_sessions(self) -> List[Dict[str, Any]]:
        url = f"{self.plex_url}/status/sessions"
        headers = {"X-Plex-Token": self.plex_token, "Accept": "application/json"}
        response = requests.get(url, headers=headers)
        response.raise_for_status()

        data = response.json()
        sessions = data.get("MediaContainer", {}).get("Metadata", [])

        parsed_sessions = []
        for session in sessions:
            parsed_session = {
                "session_id": session.get("Session", {}).get("id"),
                "user": session.get("User", {}).get("title"),
                "bitrate": session.get("Media", [{}])[0].get("bitrate", 0),
                "is_transcoding": False
            }

            # Check for transcode
            transcode_session = session.get("TranscodeSession", {})
            if transcode_session and transcode_session.get("videoDecision", "") == "transcode":
                parsed_session["is_transcoding"] = True

            # Additional check for part details if TranscodeSession isn't clear enough
            if not parsed_session["is_transcoding"]:
                for media in session.get("Media", []):
                    for part in media.get("Part", []):
                        for stream in part.get("Stream", []):
                            if stream.get("decision") == "transcode" and stream.get("streamType") == 1: # 1 is video
                                parsed_session["is_transcoding"] = True
                                break
                        if parsed_session["is_transcoding"]:
                            break
                    if parsed_session["is_transcoding"]:
                        break

            parsed_sessions.append(parsed_session)

        return parsed_sessions

class SessionTerminator:
    def __init__(self, plex_url: str, plex_token: str, dry_run: bool):
        self.plex_url = plex_url.rstrip("/")
        self.plex_token = plex_token
        self.dry_run = dry_run

    def terminate(self, session_id: str, reason: str):
        if self.dry_run:
            logging.info(f"DRY RUN: Would terminate session {session_id} for reason: {reason}")
            return

        url = f"{self.plex_url}/status/sessions/terminate"
        headers = {"X-Plex-Token": self.plex_token}
        params = {"sessionId": session_id, "reason": reason}
        try:
            response = requests.get(url, headers=headers, params=params)
            response.raise_for_status()
            logging.info(f"Successfully terminated session {session_id}. Reason: {reason}")
        except Exception as e:
            logging.error(f"Failed to terminate session {session_id}: {e}")

class ConcurrencyGovernor:
    def __init__(self, max_transcodes: int, max_streams_per_user: int, terminator: SessionTerminator):
        self.max_transcodes = max_transcodes
        self.max_streams_per_user = max_streams_per_user
        self.terminator = terminator

    def enforce(self, sessions: List[Dict[str, Any]]):
        # 1. Enforce max streams per user
        if self.max_streams_per_user is not None:
            user_sessions = {}
            for session in sessions:
                user = session.get("user")
                if user not in user_sessions:
                    user_sessions[user] = []
                user_sessions[user].append(session)

            for user, user_streams in user_sessions.items():
                if len(user_streams) > self.max_streams_per_user:
                    logging.warning(f"Max streams per user limit exceeded for user {user}: {len(user_streams)} active, max {self.max_streams_per_user}")
                    excess_streams = user_streams[self.max_streams_per_user:]
                    for session in excess_streams:
                        reason = f"Stream limit of {self.max_streams_per_user} exceeded for user {user}."
                        self.terminator.terminate(session["session_id"], reason)
                        # Remove from sessions list so we don't process it for transcode limits
                        if session in sessions:
                            sessions.remove(session)

        # 2. Enforce max transcodes
        transcoding_sessions = [s for s in sessions if s["is_transcoding"]]

        if len(transcoding_sessions) > self.max_transcodes:
            logging.warning(f"Transcode limit exceeded: {len(transcoding_sessions)} active, max {self.max_transcodes}")

            excess_sessions = transcoding_sessions[self.max_transcodes:]
            for session in excess_sessions:
                reason = "Hardware transcode limit exceeded. Please try direct play."
                self.terminator.terminate(session["session_id"], reason)
        else:
            logging.info(f"Transcode count within limits: {len(transcoding_sessions)} active, max {self.max_transcodes}")

def parse_args():
    parser = argparse.ArgumentParser(description="Plex Stream Concurrency & Bandwidth Throttler")
    parser.add_argument("--check-now", action="store_true", help="Run once and exit")
    parser.add_argument("--plex-url", type=str, help="Plex server URL (e.g. http://192.168.1.80:32400)")
    parser.add_argument("--plex-token", type=str, help="Plex server token")
    parser.add_argument("--max-transcodes", type=int, default=2, help="Maximum allowed concurrent transcodes (default: 2)")
    parser.add_argument("--max-streams-per-user", type=int, default=None, help="Maximum allowed concurrent streams per user")
    parser.add_argument("--dry-run", action="store_true", help="Do not terminate streams, just log")
    parser.add_argument("--json", action="store_true", help="Output logs in JSON format")
    return parser.parse_args()

def main():
    args = parse_args()
    setup_logging(args.json)
    logging.info(f"Starting Plex Stream Limiter with URL {args.plex_url}")

    if not args.plex_url or not args.plex_token:
        logging.error("Plex URL and token are required")
        sys.exit(1)

    auditor = PlexSessionAuditor(args.plex_url, args.plex_token)
    terminator = SessionTerminator(args.plex_url, args.plex_token, args.dry_run)
    governor = ConcurrencyGovernor(args.max_transcodes, args.max_streams_per_user, terminator)
    exporter = MetricsExporter(9116)

    if not args.check_now:
        exporter.start()

    while True:
        try:
            sessions = auditor.get_sessions()
            exporter.update(sessions)
            governor.enforce(sessions)
        except Exception as e:
            logging.error(f"Error during execution: {e}")

        if args.check_now:
            break

        time.sleep(15)

if __name__ == "__main__":
    main()
