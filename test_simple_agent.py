from __future__ import annotations
import datetime
import logging
import os, json
import sys
from dataclasses import dataclass
from typing import Literal
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    RunContext,
    WorkerOptions,
    cli,
    function_tool,
)
from livekit.plugins import openai, azure, elevenlabs, silero

# Google Sheets integration
try:
    import gspread
    from google.oauth2.service_account import Credentials
    GOOGLE_SHEETS_AVAILABLE = True
except ImportError:
    GOOGLE_SHEETS_AVAILABLE = False
    print("Warning: Google Sheets libraries not installed. Install with: pip install gspread google-auth")

load_dotenv()

@dataclass
class ClientData:
    full_name: str = ""
    phone_number: str = ""
    service_type: str = ""
    case_details: str = ""
    urgency: str = ""
    location: str = ""
    intent: str = ""  # For intent recognition
    data_collected: bool = False
    name_collected: bool = False
    greeting_done: bool = False

logger = logging.getLogger("shura-legal")

class GoogleSheetsManager:
    def __init__(self, credentials_file: str, spreadsheet_id: str):
        if not GOOGLE_SHEETS_AVAILABLE:
            raise ImportError("Google Sheets libraries not installed")
        
        self.scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        self.credentials = Credentials.from_service_account_info(credentials_file, scopes=self.scope)
        self.client = gspread.authorize(self.credentials)
        self.spreadsheet = self.client.open_by_key(spreadsheet_id)
        self.worksheet = self.spreadsheet.sheet1
        
        # Ensure headers exist
        headers = [
            'Timestamp', 'Full Name', 'Phone Number', 'Service Type', 
            'Case Details', 'Urgency', 'Location', 'Intent', 'Status'
        ]
        self.worksheet.update(values=[headers], range_name='A1:I1')
    
    def add_client_record(self, client_data: ClientData) -> bool:
        try:
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            row = [
                timestamp,
                client_data.full_name,
                client_data.phone_number,
                client_data.service_type,
                client_data.case_details,
                client_data.urgency,
                client_data.location,
                client_data.intent,
                'New Lead'
            ]
            self.worksheet.append_row(row)
            return True
        except Exception as e:
            logger.error(f"Error adding to Google Sheets: {e}")
            return False

class ShuraLegalAgent(Agent):
    def __init__(self, *, timezone: str, sheets_manager: GoogleSheetsManager = None) -> None:
        self.tz = ZoneInfo(timezone)
        self.sheets_manager = sheets_manager
        today = datetime.datetime.now(self.tz).strftime("%A, %B %d, %Y")
        
        super().__init__(
            instructions=(
                f"🎙️ أنت مساعد شورى للخدمات القانونية - منصة سعودية رائدة في الخدمات القانونية. "
                f"اليوم {today} وأنا هنا لمساعدتك في جميع احتياجاتك القانونية. "
                
                "🎯 شخصيتك: "
                "- ودود ومهني - أظهر اهتماماً حقيقياً وطاقة إيجابية "
                "- لهجة سعودية محترمة - استخدم تعابير مثل: 'أهلاً وسهلاً'، 'تشرفت'، 'يعطيك العافية'، 'والنعم' "
                "- متعاطف ومتفهم - أظهر فهمك لاحتياجات العميل "
                "- استخدم تعابير سعودية محترمة: 'أهلاً وسهلاً'، 'والنعم فيك'، 'يعطيك العافية' "
                
                "💬 أسلوب الحوار: "
                "- تحدث بطريقة طبيعية ومهنية - لا تكن روبوتياً "
                "- استخدم اسم العميل مرة واحدة فقط عند التعارف، ثم تحدث بشكل طبيعي "
                "- أضف لمسات بشرية محترمة: 'طيب'، 'تمام'، 'ممتاز'، 'أفهم' "
                "- اطرح سؤال واحد فقط وانتظر الرد "
                
                "🎧 بداية المكالمة: "
                "'السلام عليكم! أهلاً وسهلاً في شورى للخدمات القانونية. أنا مساعدك الذكي وأنا هنا لمساعدتك في جميع احتياجاتك القانونية. ممكن أعرف اسمك الكريم؟' "
                
                "📋 مهمتك الأساسية: "
                "- جمع بيانات العملاء للخدمات القانونية (اسم، جوال، نوع الخدمة، التفاصيل، الموقع) "
                "- الرد على استفسارات الأسعار والخدمات "
                "- تحويل الحالات الحرجة فقط (شكاوى، إلغاء، مشاكل تقنية، خارج السعودية) "
                
                "⚠️ الحالات الحرجة (تحويل فوري): "
                "1. شكاوى على خدمات سابقة "
                "2. طلبات إلغاء "
                "3. مشاكل تقنية "
                "4. طلبات من خارج السعودية "
                
                "⚖️ خدماتنا: "
                "استشارات قانونية، عقود، مذكرات، تمثيل قضائي، توثيق، ترجمة قانونية، تحليل قضايا، ومشير (المستشار الذكي). "
                
                "💰 الأسعار: باقات متنوعة من 149 ريال للاستشارة الأساسية. يمكنك تحميل التطبيق لمعرفة جميع التفاصيل. "
                
                "👥 محامين مرخصين من وزارة العدل السعودية. "
                "💳 طرق الدفع: مدى، أبل باي، فيزا، ماستر كارد، تقسيط عبر تمارا. "
                
                "🎯 ركز فقط على: جمع البيانات، الرد على الاستفسارات، تحويل الحالات الحرجة. لا تخرج عن هذه المهام!"
            )
        )

    def _is_critical_case(self, message: str) -> bool:
        """Check if this is a critical case that needs immediate transfer"""
        message_lower = message.lower()
        
        # Only these specific cases should be transferred
        critical_patterns = [
            # Complaints about existing service
            "ما تواصل", "ما أحد رد", "لم يتواصل", "لا يرد", "شكوى", "مشكلة مع المحامي",
            
            # Cancellation requests
            "ألغاء", "إلغاء", "وقف الاشتراك", "إيقاف الخدمة", "cancel",
            
            # Technical issues
            "التطبيق لا يعمل", "مشكلة في المنصة", "خطأ تقني", "لا يفتح", "مشكلة تقنية",
            
            # Outside Saudi Arabia
            "خارج السعودية", "من مصر", "من الكويت", "من الإمارات", "أعيش في", "مقيم في"
        ]
        
        return any(pattern in message_lower for pattern in critical_patterns)

    def _detect_intent(self, message: str) -> str:
        """Detect user intent from their message"""
        message_lower = message.lower()
        
        # Check if it's a critical case first
        if self._is_critical_case(message):
            if any(word in message_lower for word in ["ما تواصل", "ما أحد رد", "شكوى"]):
                return "شكوى"
            elif any(word in message_lower for word in ["ألغاء", "إلغاء", "وقف"]):
                return "إلغاء خدمة"
            elif any(word in message_lower for word in ["التطبيق", "مشكلة في المنصة", "تقني"]):
                return "مشكلة تقنية"
            elif any(word in message_lower for word in ["خارج السعودية", "من مصر", "من الكويت"]):
                return "خدمة خارج السعودية"
        
        # Pricing inquiry indicators
        price_keywords = ["أسعار", "كم السعر", "التكلفة", "كم يكلف", "باقات", "pricing"]
        if any(keyword in message_lower for keyword in price_keywords):
            return "سؤال عام / أسعار"
        
        # Default to service request for most cases
        service_keywords = ["استشارة", "محامي", "قضية", "عقد", "مذكرة", "توثيق", "ترجمة", "خدمة قانونية", "أحتاج", "أريد", "عندي قضية", "أبغى"]
        if any(keyword in message_lower for keyword in service_keywords):
            return "طلب خدمة داخل السعودية"
        
        return "سؤال عام"

    @function_tool
    async def transfer_call(self, ctx: RunContext["ClientData"], phone_number: str = "+966530845146") -> str:
        """
        Transfer the call to a human agent for critical cases.
        """
        ctx.disallow_interruptions()
        return f"تمام، سأحولك الآن لأحد زملائي المختصين على الرقم {phone_number}. انتظر قليلاً..."

    @function_tool
    async def collect_customer_name(
        self,
        ctx: RunContext["ClientData"],
        full_name: str = ""
    ) -> str:
        """
        Collect customer name - first step in any interaction.
        """
        if full_name:
            ctx.userdata.full_name = full_name.strip()
            ctx.userdata.name_collected = True
            return f"أهلاً وسهلاً! تشرفت فيك يا {ctx.userdata.full_name}. كيف يمكنني مساعدتك اليوم؟"
        
        return "ممكن أعرف اسمك الكريم؟"

    @function_tool
    async def handle_critical_cases_only(
        self,
        ctx: RunContext["ClientData"],
        user_request: str = "",
        phone_number: str = ""
    ) -> str:
        """
        Handle ONLY critical cases that require immediate transfer.
        This function should ONLY be called for complaints, cancellations, technical issues, or outside Saudi requests.
        """
        # Check if this is actually a critical case
        if not self._is_critical_case(user_request):
            return "طيب، هذا ليس طلب حرج. دعني أساعدك في جمع البيانات المطلوبة."
        
        # Set the critical intent
        ctx.userdata.intent = self._detect_intent(user_request)
        
        # Collect phone number if not provided
        if phone_number:
            ctx.userdata.phone_number = phone_number.strip()
        
        if not ctx.userdata.phone_number:
            return "ممكن تعطيني رقم جوالك (قول لي رقم رقم عشان أتأكد من صحته)؟"
        
        # Show empathy and transfer
        empathy_responses = {
            "شكوى": "أفهم انزعاجك وأعتذر لك عن هذا التأخير. مشكلتك مهمة بالنسبة لنا",
            "إلغاء خدمة": "تمام، فهمت رغبتك في إلغاء الخدمة",
            "مشكلة تقنية": "أعتذر لك عن هذه المشكلة التقنية",
            "خدمة خارج السعودية": "فهمت إنك تحتاج خدمة من خارج السعودية"
        }
        
        response = empathy_responses.get(ctx.userdata.intent, "فهمت طلبك")
        response += ". سأحولك الآن لأحد المختصين لمساعدتك بشكل أفضل."
        
        # Trigger call transfer
        await self.transfer_call(ctx, "+966530845146")
        return response

    @function_tool
    async def process_service_request(
        self,
        ctx: RunContext["ClientData"],
        user_message: str = ""
    ) -> str:
        """
        Main function to process service requests and collect data step by step.
        This should be the primary function for handling regular service requests.
        """
        # If this is a critical case, handle it separately
        if self._is_critical_case(user_message):
            ctx.userdata.intent = self._detect_intent(user_message)
            return await self.handle_critical_cases(ctx)
        
        # For regular service requests, collect data
        ctx.userdata.intent = "طلب خدمة داخل السعودية"
        
        # Step 1: Get name if not collected
        if not ctx.userdata.name_collected:
            return "ممكن أعرف اسمك الكريم؟"
        
        # Step 2: Get phone number
        if not ctx.userdata.phone_number:
            return "ممكن رقم جوالك (قول لي رقم رقم عشان أتأكد من صحته)؟"
        
        # Step 3: Get service type
        if not ctx.userdata.service_type:
            if "استشارة" in user_message.lower():
                return "الاستشارة بخصوص أي موضوع بالضبط؟"
            else:
                return "ممكن أعرف نوع القضية؟"
        
        # Step 4: Get case details
        if not ctx.userdata.case_details:
            return "ممكن تفاصيل مختصرة؟" if "استشارة" in ctx.userdata.service_type else "تعطيني تفاصيل بسيطة عنها؟"
        
        # Step 5: Get urgency (only for legal cases, not consultations)
        if "قضية" in ctx.userdata.service_type and not ctx.userdata.urgency:
            return "وش درجة الاستعجال عندك؟"
        
        # Step 6: Get location
        if not ctx.userdata.location:
            return "وين موقعك؟"
        
        # All data collected - save it
        ctx.userdata.data_collected = True
        return await self.save_client_data(ctx)

    @function_tool
    async def provide_pricing_info(self, ctx: RunContext["ClientData"]) -> str:
        """
        Provide pricing information for Shura legal services.
        """
        return (
            "نقدم باقات متنوعة: "
            "الاستشارة الأساسية بمئة وتسعة وأربعين ريال لمدة عشرين دقيقة مع محامي مرخص، "
            "والاستشارة الذهبية بأربعمية وتسعة وتسعين ريال، "
            "والاستشارة البلاتينية بتسعمية وتسعة وتسعين ريال لمدة خمسين دقيقة مع محامي بخبرة أكثر من عشر سنوات. "
            "يمكنك تحميل تطبيق شورى لمعرفة جميع الأسعار واختيار ما يناسبك."
        )

    @function_tool
    async def collect_service_data(
        self,
        ctx: RunContext["ClientData"],
        full_name: str  = "",
        phone_number: str = "",
        service_type: str = "",
        case_details: str = "",
        urgency: str = "",
        location: str = ""
    ) -> str:
        """
        Collect service data step by step for regular service requests.
        """
        # Update provided information
        if phone_number:
            ctx.userdata.phone_number = phone_number.strip()
        if full_name:
            ctx.userdata.full_name = full_name.strip()
        if service_type:
            ctx.userdata.service_type = service_type.strip()
        if case_details:
            ctx.userdata.case_details = case_details.strip()
        if urgency:
            ctx.userdata.urgency = urgency.strip()
        if location:
            ctx.userdata.location = location.strip()

        # Collect required fields step by step
        if not ctx.userdata.full_name:
            return "ممكن تزوّدني باسمك الثلاثي؟"
        if not ctx.userdata.phone_number:
            return "ممكن رقم جوالك (قول لي رقم رقم عشان أتأكد من صحته)؟"
        
        if not ctx.userdata.service_type:
            if any(word in (case_details or "").lower() for word in ["استشارة", "رأي قانوني"]):
                return "الاستشارة بخصوص أي موضوع بالضبط؟"
            else:
                return "ممكن أعرف نوع القضية؟"
        
        if not ctx.userdata.case_details:
            return "ممكن تفاصيل مختصرة؟" if "استشارة" in ctx.userdata.service_type else "تعطيني تفاصيل بسيطة عنها؟"
        
        if "قضية" in ctx.userdata.service_type and not ctx.userdata.urgency:
            return "وش درجة الاستعجال عندك؟"
        
        if not ctx.userdata.location:
            return "وين موقعك؟"
        
        # All required data collected - save it
        ctx.userdata.data_collected = True
        return await self.save_client_data(ctx)

    @function_tool
    async def save_client_data(
        self,
        ctx: RunContext["ClientData"]
    ) -> str:
        """
        Save collected client data to Google Sheets and confirm the consultation request.
        """
        if not ctx.userdata.data_collected:
            return "نحتاج نكمل جمع البيانات الأساسية أولاً."
        
        ctx.disallow_interruptions()
        
        # Save to Google Sheets if available
        if self.sheets_manager:
            success = self.sheets_manager.add_client_record(ctx.userdata)
            if not success:
                return "عذراً، حدث خطأ في حفظ البيانات. رجاءً حاول مرة أخرى أو تواصل معنا مباشرة."
        
        return (
            f"ممتاز! تم حفظ بياناتك بنجاح في نظام شورى للخدمات القانونية. "
            f"سنحصل لك على أفضل محامي وسنتواصل معك خلال أربع وعشرين ساعة. يعطيك العافية!"
        )

    @function_tool
    async def provide_general_info(self, ctx: RunContext["ClientData"], topic: str = "") -> str:
        """
        Provide general information about Shura platform services.
        """
        if "خدمات" in topic.lower() or "services" in topic.lower():
            return (
                "أهلاً وسهلاً! منصة شورى تقدم خدمات قانونية شاملة تشمل: "
                "الاستشارات القانونية، صياغة ومراجعة العقود، إعداد المذكرات القانونية، "
                "التمثيل القضائي، التوثيق القانوني، الترجمة القانونية، ودراسة وتحليل القضايا. "
                "كما نوفر خدمة 'مشير' - مستشارك القانوني الذكي بالذكاء الاصطناعي للاستشارات المجانية الفورية."
            )
        
        if "فريق" in topic.lower() or "محامين" in topic.lower():
            return (
                "والنعم! فريق شورى يضم نخبة من المحامين المرخصين من وزارة العدل السعودية "
                "وأعضاء في الهيئة السعودية للمحامين، بخبرة عالية وكفاءة مميزة في مختلف التخصصات القانونية."
            )
        
        return "أي معلومات محددة تحتاجها عن منصة شورى؟"  

async def entrypoint(ctx: JobContext):
    await ctx.connect()
    timezone = "Asia/Riyadh"
    
    # Initialize Google Sheets manager if credentials are available
    sheets_manager = None
    if GOOGLE_SHEETS_AVAILABLE:
        credentials_file = json.loads(os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON"))
        spreadsheet_id = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID")
        
        if credentials_file and spreadsheet_id:
            try:
                sheets_manager = GoogleSheetsManager(credentials_file, spreadsheet_id)
                logger.info("Google Sheets integration initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize Google Sheets: {e}")
        else:
            logger.warning("Google Sheets credentials not configured. Data will not be saved to sheets.")

    session = AgentSession[ClientData](
        userdata=ClientData(),
        stt=azure.STT(
            speech_key=os.getenv("AZURE_SPEECH_KEY"),
            speech_region=os.getenv("AZURE_SPEECH_REGION"),
            language=["ar-SA"]  # Arabic (Saudi Arabia)
        ),
        llm=openai.LLM(
            model="gpt-4o", 
            parallel_tool_calls=False, 
            temperature=0.6
        ),
        tts=azure.TTS(
            speech_key=os.getenv("AZURE_SPEECH_KEY"),
            speech_region=os.getenv("AZURE_SPEECH_REGION"),
            language="ar-SA",
            voice="ar-SA-HamedNeural"
        ),
        vad=silero.VAD.load(),
        max_tool_steps=2,  # Increased to allow for intent recognition + action
    )
    
    await session.start(
        agent=ShuraLegalAgent(timezone=timezone, sheets_manager=sheets_manager), 
        room=ctx.room
    )

if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))