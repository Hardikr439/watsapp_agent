import os
import json
import requests
import google.generativeai as genai

class ServiceResult:
    """Result object for WhatsApp agent service"""
    def __init__(self, receiver: str, original_content: str, formatted_content: str, sent: bool):
        self.receiver = receiver
        self.original_content = original_content
        self.formatted_content = formatted_content
        self.sent = sent
        self.raw = formatted_content
        self.json_dict = {
            "receiver": receiver,
            "original_content": original_content,
            "formatted_content": formatted_content,
            "sent": sent,
            "task": "whatsapp_agent"
        }

class AgenticService:
    """WhatsApp agent service that uses Gemini to format content and sends via WhatsApp"""
    
    def __init__(self, logger=None):
        self.logger = logger
        # Initialize Gemini API client
        # The client automatically gets the API key from the environment variable GEMINI_API_KEY
        # Reference: https://ai.google.dev/gemini-api/docs/quickstart
        # Check both os.getenv and os.environ (common pattern from GitHub projects)
        gemini_api_key = os.getenv("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY", "")
        if not gemini_api_key or not gemini_api_key.strip():
            if self.logger:
                self.logger.error("GEMINI_API_KEY environment variable is not set")
            raise ValueError("GEMINI_API_KEY environment variable is required")
        
        # Configure the Gemini API
        # Reference: https://ai.google.dev/gemini-api/docs/quickstart
        genai.configure(api_key=gemini_api_key)
        
        # WbizTool API configuration
        # Reference: https://wbiztool.com/docs/
        # Required fields: client_id, api_key, whatsapp_client
        self.wbiztool_client_id = (os.getenv("WBIZTOOL_CLIENT_ID") or os.environ.get("WBIZTOOL_CLIENT_ID", "")).strip()
        self.wbiztool_api_key = (os.getenv("WBIZTOOL_API_KEY") or os.environ.get("WBIZTOOL_API_KEY", "")).strip()
        self.wbiztool_whatsapp_client = (os.getenv("WBIZTOOL_WHATSAPP_CLIENT") or os.environ.get("WBIZTOOL_WHATSAPP_CLIENT", "")).strip()
        
        # WbizTool API endpoint
        self.wbiztool_api_url = "https://wbiztool.com/api/v1/send_msg/"
        
        # Debug logging for WbizTool configuration
        if self.logger:
            if not self.wbiztool_client_id:
                self.logger.warning("WBIZTOOL_CLIENT_ID is not set or is empty")
            else:
                self.logger.debug(f"WBIZTOOL_CLIENT_ID is set: {self.wbiztool_client_id}")
            
            if not self.wbiztool_api_key:
                self.logger.warning("WBIZTOOL_API_KEY is not set or is empty")
            else:
                self.logger.debug(f"WBIZTOOL_API_KEY is set (length: {len(self.wbiztool_api_key)})")
            
            if not self.wbiztool_whatsapp_client:
                self.logger.warning("WBIZTOOL_WHATSAPP_CLIENT is not set or is empty")
            else:
                self.logger.debug(f"WBIZTOOL_WHATSAPP_CLIENT is set: {self.wbiztool_whatsapp_client}")
    
    async def _format_with_gemini(self, content: str) -> str:
        """
        Format content using Gemini AI
        
        Args:
            content: Original content to format
            
        Returns:
            Formatted content string
        """
        try:
            if self.logger:
                self.logger.info(f"Formatting content with Gemini: '{content[:100]}{'...' if len(content) > 100 else ''}'")
            
            prompt = f"Format the following content in a clear, professional, and well-structured way. Make it easy to read and understand:\n\n{content}"
            
            # Use the google-generativeai SDK
            # Reference: https://ai.google.dev/gemini-api/docs/quickstart
            model = genai.GenerativeModel("gemini-2.5-flash")
            response = model.generate_content(prompt)
            formatted_text = response.text
            
            if self.logger:
                self.logger.info(f"Gemini formatting completed: '{formatted_text[:100]}{'...' if len(formatted_text) > 100 else ''}'")
            
            return formatted_text
        except Exception as e:
            if self.logger:
                self.logger.error(f"Error formatting with Gemini: {str(e)}", exc_info=True)
            # Return original content if Gemini fails
            return content
    
    def _extract_country_code_and_phone(self, phone_number: str) -> tuple:
        """
        Extract country code and phone number for WbizTool API
        Reference: https://wbiztool.com/docs/
        
        Args:
            phone_number: Phone number (may include +, spaces, dashes, etc.)
            
        Returns:
            Tuple of (country_code, phone_number) as strings
        """
        # Remove all non-digit characters except +
        cleaned = phone_number.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
        
        # Extract digits only
        digits = ''.join(filter(str.isdigit, cleaned))
        
        # Common country codes (1-3 digits)
        # Try to extract country code (1-3 digits)
        if cleaned.startswith("+"):
            # Has + sign, try to extract country code
            # Common patterns: +1 (US), +91 (India), +44 (UK), etc.
            if digits.startswith("1") and len(digits) == 11:
                return ("1", digits[1:])
            elif digits.startswith("91") and len(digits) >= 10:
                return ("91", digits[2:])
            elif len(digits) >= 10:
                # Try 2-digit country code (most common)
                if digits.startswith(("44", "49", "33", "39", "34", "31", "32", "41", "43", "45", "46", "47", "48")):
                    return (digits[:2], digits[2:])
                # Try 1-digit country code
                elif digits.startswith(("1", "7")):
                    return (digits[:1], digits[1:])
                # Try 3-digit country code
                elif digits.startswith(("880", "966", "971", "974", "961", "962", "965", "968")):
                    return (digits[:3], digits[3:])
        
        # Default: assume no country code, use first digits as country code
        # For India (91), if number starts with 9 and is 10 digits, assume country code 91
        if len(digits) == 10 and digits[0] == "9":
            return ("91", digits)
        elif len(digits) == 11 and digits[0] == "1":
            return ("1", digits[1:])
        
        # Fallback: return as-is with empty country code
        return ("", digits)
    
    async def _send_whatsapp_message(self, receiver: str, message: str, preview_url: bool = False) -> bool:
        """
        Send WhatsApp message to receiver using WbizTool API
        Reference: https://wbiztool.com/docs/
        
        Args:
            receiver: WhatsApp phone number (with country code, e.g., +1234567890)
            message: Message content to send
            preview_url: Not used in WbizTool API (kept for compatibility)
            
        Returns:
            True if message sent successfully, False otherwise
        """
        try:
            if not self.wbiztool_client_id:
                if self.logger:
                    self.logger.warning("WBIZTOOL_CLIENT_ID not configured, skipping WhatsApp send")
                return False
            
            if not self.wbiztool_api_key:
                if self.logger:
                    self.logger.warning("WBIZTOOL_API_KEY not configured, skipping WhatsApp send")
                return False
            
            if not self.wbiztool_whatsapp_client:
                if self.logger:
                    self.logger.warning("WBIZTOOL_WHATSAPP_CLIENT not configured, skipping WhatsApp send")
                return False
            
            # Extract country code and phone number
            country_code, phone = self._extract_country_code_and_phone(receiver)
            
            if self.logger:
                self.logger.info(f"Sending WhatsApp message to {phone} (country code: {country_code}, original: {receiver})")
            
            # WbizTool API payload format
            # Reference: https://wbiztool.com/docs/send-message-api/
            # Required fields: client_id, api_key, whatsapp_client, phone, country_code, msg, msg_type
            payload = {
                "client_id": int(self.wbiztool_client_id),
                "api_key": self.wbiztool_api_key,
                "whatsapp_client": int(self.wbiztool_whatsapp_client),
                "phone": phone,
                "country_code": country_code,
                "msg": message,
                "msg_type": 0  # 0 for text message
            }
            
            if self.logger:
                self.logger.debug(f"Sending WbizTool request to {self.wbiztool_api_url}")
                # Don't log full payload with API key for security
                debug_payload = {k: v if k != "api_key" else "***" for k, v in payload.items()}
                self.logger.debug(f"Payload: {json.dumps(debug_payload, indent=2)}")
            
            # Send request using requests library (form data, not JSON)
            # WbizTool API expects form data
            response = requests.post(
                self.wbiztool_api_url,
                data=payload,
                timeout=30
            )
            
            # Check response status
            if response.status_code == 200:
                try:
                    response_data = response.json()
                    # Handle status as string or integer
                    status_value = response_data.get("status", "")
                    if isinstance(status_value, int):
                        status = str(status_value)
                    else:
                        status = str(status_value).lower() if status_value else ""
                    
                    # Check for success (status can be "success", "1", 1, or message_id present)
                    if status == "success" or status == "1" or response_data.get("message_id"):
                        if self.logger:
                            self.logger.info(f"WhatsApp message sent successfully to {phone}")
                            if "message_id" in response_data:
                                self.logger.debug(f"WbizTool message ID: {response_data['message_id']}")
                            self.logger.debug(f"WbizTool API response: {response_data}")
                        return True
                    else:
                        # API returned 200 but with error status
                        error_message = response_data.get("message", "Unknown error")
                        if self.logger:
                            self.logger.error(f"WbizTool API error: {error_message}")
                            self.logger.debug(f"Full response: {response_data}")
                        return False
                except json.JSONDecodeError:
                    if self.logger:
                        self.logger.error(f"Failed to parse JSON response: {response.text}")
                    return False
            else:
                # HTTP error
                try:
                    error_data = response.json()
                    error_message = error_data.get("message", f"HTTP {response.status_code}")
                    if self.logger:
                        self.logger.error(f"WbizTool API error [{response.status_code}]: {error_message}")
                except:
                    if self.logger:
                        self.logger.error(f"WbizTool API error: {response.status_code} - {response.text}")
                return False
                
        except requests.exceptions.RequestException as e:
            if self.logger:
                self.logger.error(f"Network error sending WhatsApp message: {str(e)}", exc_info=True)
            return False
        except Exception as e:
            if self.logger:
                self.logger.error(f"Error sending WhatsApp message: {str(e)}", exc_info=True)
            return False
    
    async def execute_task(self, input_data: dict) -> ServiceResult:
        """
        Execute WhatsApp agent task
        
        Args:
            input_data: Dictionary containing 'receiver' and 'content' keys
            
        Returns:
            ServiceResult with formatted content and send status
        """
        receiver = input_data.get("receiver", "")
        content = input_data.get("content", "")
        
        if not receiver:
            if self.logger:
                self.logger.error("Receiver parameter is missing")
            raise ValueError("Receiver parameter is required")
        
        if not content:
            if self.logger:
                self.logger.error("Content parameter is missing")
            raise ValueError("Content parameter is required")
        
        if self.logger:
            self.logger.info(f"Processing WhatsApp agent task for receiver: {receiver}")
        
        # Format content with Gemini
        formatted_content = await self._format_with_gemini(content)
        
        # Send formatted message via WhatsApp
        sent = await self._send_whatsapp_message(receiver, formatted_content)
        
        if self.logger:
            self.logger.info(f"WhatsApp agent task completed. Sent: {sent}")
        
        return ServiceResult(receiver, content, formatted_content, sent)

def get_agentic_service(logger=None):
    """
    Factory function to get the WhatsApp agent service
    """
    return AgenticService(logger)