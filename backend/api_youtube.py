"""Protected operator YouTube settings and OAuth callback.

OAuth callback alone is unauthenticated because Google redirects the browser,
but it requires a short-lived, single-use high-entropy PKCE state created by
a bearer-authenticated operator action.
"""
from fastapi import APIRouter,HTTPException
from pydantic import BaseModel,Field
from backend import core as db
from backend.youtube_data import (
    YouTubeError,status,test_key,oauth_state,oauth_disconnect
)

router=APIRouter(prefix='/api/youtube')


class KeyInput(BaseModel):
    key:str=Field(min_length=16,max_length=200)


class OAuthBegin(BaseModel):
    redirect_uri:str=Field(min_length=12,max_length=500)


class ClientSettings(BaseModel):
    client_id:str=Field(min_length=10,max_length=500)
    client_secret:str=Field(min_length=10,max_length=500)


@router.get('/status')
def connection_status():
    return status()


@router.put('/key')
def put_key(body:KeyInput):
    db.set_secret('youtube_api_key',body.key.strip())
    return status()


@router.delete('/key')
def drop_key():
    db.set_secret('youtube_api_key','')
    return status()


@router.post('/key/test')
def check_key():
    return test_key()


@router.put('/oauth/client')
def put_client(body:ClientSettings):
    db.set_secret('youtube_client_id',body.client_id.strip())
    db.set_secret('youtube_client_secret',body.client_secret.strip())
    return {'configured':True}


@router.post('/oauth/begin')
def begin(body:OAuthBegin):
    try:return {'authorization_url':oauth_state(body.redirect_uri)}
    except ValueError as exc:raise HTTPException(422,str(exc)) from None


@router.delete('/oauth')
def disconnect():
    return oauth_disconnect()
