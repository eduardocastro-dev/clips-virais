"""Upload/inspect the nine PNG scenario templates from the operator's ZIP."""
from fastapi import APIRouter,UploadFile,File,HTTPException
from backend.template_pack import install_zip,status,MAX_ZIP

router=APIRouter(prefix='/api/templates')


@router.get('/package')
def get_installed_package():
    return status()


@router.post('/package')
async def upload_package(file:UploadFile=File(...)):
    filename=(file.filename or '').lower()
    if not filename.endswith('.zip'):
        raise HTTPException(422,'Envie gta_studio_templates.zip.')
    raw=await file.read(MAX_ZIP+1)
    if len(raw)>MAX_ZIP:raise HTTPException(413,'ZIP excede 24 MB.')
    try:return install_zip(raw)
    except (ValueError,OSError) as exc:
        raise HTTPException(422,str(exc)) from None
