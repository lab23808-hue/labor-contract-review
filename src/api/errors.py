"""API 异常映射与统一异常处理器。"""

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from domain.document.parser import DocumentParseError, UnsupportedFormatError
from domain.modification.service import ModificationConflictError, ModificationServiceError
from infra.storage import ContractError, ContractNotFoundError


def _response(exc: Exception, status_code: int) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"detail": str(exc)})


async def handle_contract_not_found(request: Request, exc: ContractNotFoundError) -> JSONResponse:
    return _response(exc, status.HTTP_404_NOT_FOUND)


async def handle_unsupported_format(request: Request, exc: UnsupportedFormatError) -> JSONResponse:
    return _response(exc, status.HTTP_415_UNSUPPORTED_MEDIA_TYPE)


async def handle_not_implemented(request: Request, exc: NotImplementedError) -> JSONResponse:
    return _response(exc, status.HTTP_415_UNSUPPORTED_MEDIA_TYPE)


async def handle_document_parse(request: Request, exc: DocumentParseError) -> JSONResponse:
    return _response(exc, status.HTTP_422_UNPROCESSABLE_ENTITY)


async def handle_modification_error(request: Request, exc: ModificationServiceError) -> JSONResponse:
    return _response(exc, status.HTTP_409_CONFLICT)


async def handle_contract_error(request: Request, exc: ContractError) -> JSONResponse:
    return _response(exc, status.HTTP_422_UNPROCESSABLE_ENTITY)


def install_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ContractNotFoundError, handle_contract_not_found)
    app.add_exception_handler(UnsupportedFormatError, handle_unsupported_format)
    app.add_exception_handler(NotImplementedError, handle_not_implemented)
    app.add_exception_handler(DocumentParseError, handle_document_parse)
    app.add_exception_handler(ModificationConflictError, handle_modification_error)
    app.add_exception_handler(ModificationServiceError, handle_modification_error)
    app.add_exception_handler(ContractError, handle_contract_error)
