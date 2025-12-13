from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import json
import os
import requests

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        # Parse query parameters
        query = urlparse(self.path).query
        params = parse_qs(query)
        user_id = params.get('userid', [None])[0]
        
        if not user_id:
            self.send_response(400)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Missing userid"}).encode())
            return
        
        # Update balance in Supabase
        supabase_url = os.environ.get('SUPABASE_URL')
        supabase_key = os.environ.get('SUPABASE_KEY')
        
        headers = {
            'apikey': supabase_key,
            'Authorization': f'Bearer {supabase_key}',
            'Content-Type': 'application/json'
        }
        
        # Add 0.05 SUI reward
        rpc_url = f"{supabase_url}/rest/v1/rpc/add_balance"
        payload = {'user_id': int(user_id), 'amount': 0.05}
        
        response = requests.post(rpc_url, headers=headers, json=payload)
        
        # Update last_ad_watch
        from datetime import datetime, timezone
        update_url = f"{supabase_url}/rest/v1/users?telegram_id=eq.{user_id}"
        update_data = {'last_ad_watch': datetime.now(timezone.utc).isoformat()}
        requests.patch(update_url, headers=headers, json=update_data)
        
        # Send success response
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps({
            "success": True,
            "user_id": user_id,
            "reward": "0.05 SUI"
        }).encode())
