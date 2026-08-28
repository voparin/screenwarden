import secrets
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

security = HTTPBasic()


def make_auth_checker(password: str):
    def check_auth(credentials: HTTPBasicCredentials = Depends(security)):
        correct = secrets.compare_digest(credentials.password.encode(), password.encode())
        if not correct:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect password",
                headers={"WWW-Authenticate": "Basic"},
            )
        return credentials.username
    return check_auth
