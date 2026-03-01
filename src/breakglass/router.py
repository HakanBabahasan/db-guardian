"""
DB Guardian — Break-Glass API Router.

Endpoints:
  GET  /api/breakglass/status/{job_id}  — Oturum durumu
  POST /api/breakglass/approve          — Yönetici onayı
  GET  /api/breakglass/daily-password   — Günlük parola (admin/test)
"""
from fastapi import APIRouter, Depends, HTTPException, status

from src.breakglass.manager import breakglass_manager
from src.gateway.auth import generate_daily_password, get_current_user, require_role
from src.models.schemas import BreakGlassApprove, BreakGlassStatusResponse

router = APIRouter(prefix="/api/breakglass", tags=["Break-Glass"])


@router.get("/status/{job_id}", response_model=BreakGlassStatusResponse)
def get_breakglass_status(
    job_id: str,
    _user=Depends(require_role("admin", "manager")),
):
    """Break-glass oturum durumunu sorgular."""
    session = breakglass_manager.get_session(job_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Break-glass oturumu bulunamadı: {job_id}",
        )
    return BreakGlassStatusResponse(
        job_id=session.job_id,
        status=session.status,
        approvals=session.approvals,
        required_approvals=2,
        expires_at=session.expires_at,
        message=f"{len(session.approvals)}/2 onay alındı.",
    )


@router.post("/approve")
def approve_breakglass(
    req: BreakGlassApprove,
    current_user=Depends(get_current_user),
):
    """
    Yönetici onayı verir.
    İki farklı yönetici onayladıktan sonra iş production'a uygulanır.
    """
    # Onaylayan kullanıcının token'daki ismiyle request body'deki eşleşmeli
    if current_user["username"] != req.manager_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token sahibi ile onaylayan yönetici uyuşmuyor.",
        )

    if current_user["role"] not in ("manager", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Sadece yönetici veya admin onay verebilir.",
        )

    success, message = breakglass_manager.approve(
        req.job_id, req.manager_id, req.daily_password
    )

    if not success:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)

    return {"job_id": req.job_id, "message": message}


@router.get("/daily-password/{username}")
def get_daily_password(
    username: str,
    _admin=Depends(require_role("admin")),
):
    """
    Belirtilen yöneticinin bugünkü parolasını döner.
    SADECE admin kullanabilir — test/debug amaçlı.
    """
    try:
        pwd = generate_daily_password(username)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return {"username": username, "daily_password": pwd, "note": "Bu endpointi production'da devre dışı bırakın."}
