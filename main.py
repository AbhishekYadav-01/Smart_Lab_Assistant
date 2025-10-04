# main.py
from datetime import timedelta , datetime, time
import fastapi
import asyncio
import json
from typing import List, Optional
from fastapi import Request, Depends, HTTPException, status, Query, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import sqlalchemy
from pydantic import BaseModel, EmailStr
import os

from simulation import MultiAgentTrafficSystem

from database import database, engine, metadata
from models import users, labs, bookings
from auth import pwd_context
from fastapi.security import OAuth2PasswordRequestForm
from auth import (
    User,
    Token,
    UserInDB,
    verify_password,
    create_access_token,
    ACCESS_TOKEN_EXPIRE_MINUTES,
    get_current_active_user,
    oauth2_scheme,
    create_user,
    get_current_user_from_cookie,
)

app = fastapi.FastAPI()
templates = Jinja2Templates(directory="templates")

class LabCreate(BaseModel):
    name: str
    capacity: int
    description: Optional[str] = None
    equipment: Optional[str] = None
    operating_start_time: Optional[time] = None
    operating_end_time: Optional[time] = None

class LabUpdate(BaseModel):
    name: Optional[str] = None
    capacity: Optional[int] = None
    description: Optional[str] = None
    equipment: Optional[str] = None
    operating_start_time: Optional[time] = None
    operating_end_time: Optional[time] = None

@app.get("/api/users/me", response_model=User)
async def read_users_me(current_user: User = Depends(get_current_active_user)):
    """
    Get the current authenticated user's profile data.
    """
    return current_user

class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    email: Optional[EmailStr] = None

class PasswordChange(BaseModel):
    current_password: str
    new_password: str

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[fastapi.WebSocket] = []

    async def connect(self, websocket: fastapi.WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: fastapi.WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        send_tasks = [connection.send_text(message) for connection in self.active_connections]
        results = await asyncio.gather(*send_tasks, return_exceptions=True)

        for i in range(len(self.active_connections) - 1, -1, -1):
            if isinstance(results[i], Exception):
                self.active_connections.pop(i)

manager = ConnectionManager()

@app.get("/", response_class=RedirectResponse)
async def read_root():
    """Redirects the root URL to the login page."""
    return RedirectResponse(url="/login")

@app.get("/dashboard", response_class=HTMLResponse)
async def read_dashboard(request: Request):
    """Serves the main HTML dashboard page."""
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})

@app.get("/profile", response_class=HTMLResponse)
async def profile_page(request: Request):
    return templates.TemplateResponse("profile.html", {"request": request})

@app.put("/api/users/me", response_model=User)
async def update_current_user(user_update: UserUpdate, current_user: User = Depends(get_current_active_user)):
    """
    Update the current user's full name or email.
    """
    update_data = user_update.dict(exclude_unset=True)
    
    if "email" in update_data:
        existing_user_query = users.select().where(users.c.email == update_data["email"])
        existing_user = await database.fetch_one(existing_user_query)
        if existing_user and existing_user.id != current_user.id:
            raise HTTPException(status_code=400, detail="Email already registered by another user.")

    if not update_data:
        return current_user

    query = users.update().where(users.c.username == current_user.username).values(**update_data)
    await database.execute(query)

    updated_user = await database.fetch_one(users.select().where(users.c.username == current_user.username))
    return updated_user

@app.get("/api/labs", response_model=List[LabCreate])
async def get_all_labs():
    query = labs.select()
    return await database.fetch_all(query)

@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request, current_user: User = Depends(get_current_user_from_cookie)):
    if current_user.role != "super_admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to access this page")
    
    all_users = await database.fetch_all(users.select())
    all_labs = await database.fetch_all(labs.select())

    query = sqlalchemy.select(
        bookings.c.id,
        bookings.c.start_time,
        bookings.c.end_time,
        bookings.c.student_count,
        users.c.full_name.label('booked_by_name'),
        labs.c.name.label('lab_name')
    ).select_from(
        bookings.join(users, bookings.c.user_id == users.c.id)
        .join(labs, bookings.c.lab_id == labs.c.id)
    ).order_by(sqlalchemy.desc(bookings.c.start_time))
    all_bookings = await database.fetch_all(query)

    return templates.TemplateResponse("admin.html", {
        "request": request, 
        "users": all_users, 
        "labs": all_labs,
        "bookings": all_bookings
    })

@app.post("/token", response_model=Token)
async def login_for_access_token(response: Response, form_data: OAuth2PasswordRequestForm = Depends()):
    query = users.select().where(users.c.username == form_data.username)
    user_record = await database.fetch_one(query)
    if not user_record or not verify_password(form_data.password, user_record['hashed_password']):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user_record['username']}, expires_delta=access_token_expires
    )

    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        samesite="lax",
    )
    
    return {"access_token": access_token, "token_type": "bearer"}

class UserCreate(BaseModel):
    username: str
    full_name: str
    email: str
    password: str
    role: str

@app.post("/register", status_code=status.HTTP_201_CREATED)
async def register_user(user: UserCreate):
    if not user.email.endswith("@iitj.ac.in"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid email domain. Only @iitj.ac.in is allowed."
        )
    query = users.select().where(users.c.username == user.username)
    if await database.fetch_one(query):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered."
        )
    query = users.select().where(users.c.email == user.email)
    if await database.fetch_one(query):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered."
        )

    await create_user(user)
    return {"message": "User created successfully."}

@app.post("/api/labs", status_code=status.HTTP_201_CREATED)
async def create_lab(lab: LabCreate, current_user: User = Depends(get_current_active_user)):
    if current_user.role != "super_admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")
    query = labs.insert().values(**lab.dict())
    await database.execute(query)
    await manager.broadcast(json.dumps({"type": "labs_updated"}))
    return {"message": "Lab created successfully."}

@app.put("/api/labs/{lab_id}", status_code=status.HTTP_200_OK)
async def update_lab(lab_id: int, lab: LabUpdate, current_user: User = Depends(get_current_active_user)):
    if current_user.role != "super_admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")
    query = labs.update().where(labs.c.id == lab_id).values(**lab.dict(exclude_unset=True))
    await database.execute(query)
    return {"message": "Lab updated successfully."}

@app.delete("/api/labs/{lab_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lab(lab_id: int, current_user: User = Depends(get_current_active_user)):
    if current_user.role != "super_admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")
    
    delete_bookings_query = bookings.delete().where(bookings.c.lab_id == lab_id)
    await database.execute(delete_bookings_query)
    
    delete_lab_query = labs.delete().where(labs.c.id == lab_id)
    await database.execute(delete_lab_query)
    await manager.broadcast(json.dumps({"type": "labs_updated"}))

@app.put("/api/users/{user_id}", status_code=status.HTTP_200_OK)
async def update_user(user_id: int, role: str, current_user: User = Depends(get_current_active_user)):
    if current_user.role != "super_admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")
    query = users.update().where(users.c.id == user_id).values(role=role)
    await database.execute(query)
    return {"message": "User updated successfully."}

@app.post("/api/users/change-password")
async def change_current_user_password(password_data: PasswordChange, current_user: User = Depends(get_current_active_user)):
    """
    Change the current user's password.
    """
    user_in_db = await database.fetch_one(users.select().where(users.c.username == current_user.username))
    
    if not verify_password(password_data.current_password, user_in_db['hashed_password']):
        raise HTTPException(status_code=400, detail="Incorrect current password.")

    new_hashed_password = pwd_context.hash(password_data.new_password)
    query = users.update().where(users.c.username == current_user.username).values(hashed_password=new_hashed_password)
    await database.execute(query)
    
    return {"message": "Password updated successfully."}

@app.delete("/api/bookings/{booking_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_booking(booking_id: int, current_user: User = Depends(get_current_active_user)):
    if current_user.role != "super_admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")
    query = bookings.delete().where(bookings.c.id == booking_id)
    await database.execute(query)

@app.websocket("/ws")
async def websocket_endpoint(websocket: fastapi.WebSocket, token: str = Query(None)):
    """
    Handles the persistent WebSocket connection and user authentication.
    """
    if token is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    try:
        current_user = await get_current_active_user(token)
    except HTTPException:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await manager.connect(websocket)
    system = MultiAgentTrafficSystem(current_user=current_user, manager=manager)
    await system.initialize_system()

    await websocket.send_text(json.dumps({
        "type": "auth_success",
        "data": {"username": current_user.username, "role": current_user.role, "full_name": current_user.full_name}
    }))

    today = datetime.now()
    start_of_week = today - timedelta(days=today.weekday())
    end_of_week = start_of_week + timedelta(days=7)
    initial_schedule = await system.get_schedule_for_range(start_of_week, end_of_week)
    await websocket.send_text(json.dumps({"type": "schedule_update", "data": initial_schedule}))

    try:

        while True:
            data = await websocket.receive_text()
            message = json.loads(data)

            if message.get("type") == "get_schedule_for_range":
                start_date = datetime.fromisoformat(message["data"]["start"])
                end_date = datetime.fromisoformat(message["data"]["end"])
                schedule_data = await system.get_schedule_for_range(start_date, end_date)
                await websocket.send_text(json.dumps({"type": "schedule_update", "data": schedule_data}))
            
            elif message.get("type") == "update_student_count":
                await system.handle_student_count_update(message.get("data"), websocket)

            elif message.get("type") == "user_query":
                await system.handle_availability_query(message.get("data"), websocket)
            elif message.get("type") == "request_shift":
                await system.handle_shift_request(message.get("data"), websocket)
            elif message.get("type") == "book_slot":
                await system.handle_booking_request(message.get("data"), websocket)
            elif message.get("type") == "cancel_booking":
                try:
                    data = message.get("data", {})
                    result = await system.handle_cancellation_request(data, websocket)
                    if not result.get("ok"):
                        await websocket.send_text(json.dumps({"type":"error","data": result.get("error","Cancel failed")}))
                        continue

                    await websocket.send_text(json.dumps({"type":"booking_confirmation","data":{"message":"Booking cancelled.","booking_id": result.get("booking_id")}}))

                    now = datetime.now()
                    start_of_week = now - timedelta(days=now.weekday())
                    end_of_week = start_of_week + timedelta(days=7)
                    updated_schedule = await system.get_schedule_for_range(start_of_week, end_of_week)
                    await manager.broadcast(json.dumps({"type":"schedule_update", "data": updated_schedule}))
                except Exception as e:
                    await websocket.send_text(json.dumps({"type":"error","data": str(e)}))

            elif message.get("type") == "get_full_schedule":
                full_schedule_data = system.get_full_schedule()
                await websocket.send_text(json.dumps({"type": "full_schedule_update", "data": full_schedule_data}))

    except fastapi.WebSocketDisconnect:
        manager.disconnect(websocket)

@app.on_event("startup")
async def startup():
    await database.connect()
    metadata.create_all(bind=engine)

    async with database.transaction():
        admin_username = os.getenv("ADMIN_USERNAME", "admin")
        query = users.select().where(users.c.username == admin_username)
        if not await database.fetch_one(query):
            admin_user = {
                "username": admin_username,
                "full_name": "Super Admin",
                "email": os.getenv("ADMIN_EMAIL", "admin@iitj.ac.in"),
                "hashed_password": pwd_context.hash(os.getenv("ADMIN_PASSWORD", "admin123")),
                "role": "super_admin"
            }
            await database.execute(query=users.insert(), values=admin_user)

@app.post("/api/users/admin-create", status_code=status.HTTP_201_CREATED)
async def admin_create_user(user: UserCreate, current_user: User = Depends(get_current_active_user)):
    if current_user.role != "super_admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")

    if not user.email.endswith("@iitj.ac.in"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid email domain.")
    
    query = users.select().where(users.c.username == user.username)
    if await database.fetch_one(query):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Username already registered.")
        
    query = users.select().where(users.c.email == user.email)
    if await database.fetch_one(query):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered.")

    await create_user(user)
    
    await manager.broadcast(json.dumps({"type": "users_updated"}))
    
    return {"message": "User created successfully by admin."}

@app.delete("/users/delete/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(user_id: int, current_user: User = Depends(get_current_active_user)):
    if current_user.role != "super_admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")

    target_user_query = users.select().where(users.c.id == user_id)
    target_user = await database.fetch_one(target_user_query)

    if not target_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if target_user['role'] == 'super_admin':
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot delete a super admin")

    delete_bookings_query = bookings.delete().where(bookings.c.user_id == user_id)
    await database.execute(delete_bookings_query)

    delete_user_query = users.delete().where(users.c.id == user_id)
    await database.execute(delete_user_query)
    await manager.broadcast(json.dumps({"type": "users_updated"}))

@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()