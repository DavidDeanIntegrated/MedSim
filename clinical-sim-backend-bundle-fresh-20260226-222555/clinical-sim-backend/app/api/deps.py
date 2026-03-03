from functools import lru_cache

from app.core.config import get_settings
from app.domain.case_loader import CaseLoader
from app.repositories.session_repo import SessionRepository
from app.services.engine_service import EngineService
from app.services.parser_service import ParserService
from app.services.report_service import ReportService
from app.services.session_service import SessionService
from app.services.voice_service import VoiceService


@lru_cache
def get_session_repo() -> SessionRepository:
    settings = get_settings()
    return SessionRepository(settings.session_dir)


@lru_cache
def get_case_loader() -> CaseLoader:
    settings = get_settings()
    return CaseLoader(settings.data_dir / "cases")


@lru_cache
def get_session_service() -> SessionService:
    return SessionService(get_session_repo(), get_case_loader())


@lru_cache
def get_parser_service() -> ParserService:
    return ParserService()


@lru_cache
def get_llm_parser_service():
    from app.services.llm_parser_service import LLMParserService
    return LLMParserService()


@lru_cache
def get_engine_service() -> EngineService:
    return EngineService()


@lru_cache
def get_voice_service() -> VoiceService:
    return VoiceService()


@lru_cache
def get_report_service() -> ReportService:
    return ReportService()
