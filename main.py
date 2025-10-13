# main.py
from datetime import timedelta , datetime, time , timezone 
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
from auth import OrganizationCreate
from models import organizations

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
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

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
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        disconnected_connections = []
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except RuntimeError:
                disconnected_connections.append(connection)
        for connection in disconnected_connections:
            self.disconnect(connection)

manager = ConnectionManager()

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    """Serves the new landing page."""
    return templates.TemplateResponse("landing.html", {"request": request})


@app.get("/org-register", response_class=HTMLResponse)
async def org_register_page(request: Request):
    return templates.TemplateResponse("org_register.html", {"request": request})

@app.get("/org-login", response_class=HTMLResponse)
async def org_login_page(request: Request):
    return templates.TemplateResponse("org_login.html", {"request": request})

@app.get("/dashboard", response_class=HTMLResponse)
async def read_dashboard(request: Request):
    """Serves the main HTML dashboard page."""
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    orgs = await database.fetch_all(organizations.select())
    return templates.TemplateResponse("login.html", {"request": request, "organizations": orgs})

@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    orgs = await database.fetch_all(organizations.select())
    return templates.TemplateResponse("register.html", {"request": request, "organizations": orgs})

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
    if current_user.role not in ["org_admin", "super_admin"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to access this page")

    org_id = current_user.organization_id

    all_users = await database.fetch_all(users.select().where(users.c.organization_id == org_id))
    all_labs = await database.fetch_all(labs.select().where(labs.c.organization_id == org_id))

    # --- THIS IS THE CORRECTED QUERY ---
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
    ).where(
        bookings.c.organization_id == org_id
    ).order_by(
        sqlalchemy.desc(bookings.c.start_time)
    )
    # --- END OF CORRECTION ---
    
    all_bookings = await database.fetch_all(query)

    return templates.TemplateResponse("admin.html", {
        "request": request,
        "users": all_users,
        "labs": all_labs,
        "bookings": all_bookings
    })

@app.post("/org-token", response_model=Token)
async def login_for_org_admin_token(response: Response, form_data: OAuth2PasswordRequestForm = Depends()):
    # Find a user with the given username who is an 'org_admin'
    query = users.select().where(
        users.c.username == form_data.username,
        users.c.role == "org_admin" # IMPORTANT: Only allow org_admins to use this login
    )
    user_record = await database.fetch_one(query)

    if not user_record or not verify_password(form_data.password, user_record['hashed_password']):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password, or you are not an Organization Admin.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # The user is a valid org_admin, create their token
    token_data = {"sub": user_record['username'], "org_id": user_record['organization_id']}
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data=token_data, expires_delta=access_token_expires
    )

    response.set_cookie(key="access_token", value=access_token, httponly=True, samesite="lax")
    return {"access_token": access_token, "token_type": "bearer"}

@app.post("/token", response_model=Token)
async def login_for_access_token(response: Response, form_data: OAuth2PasswordRequestForm = Depends()):
    # The organization_id is now passed in the 'scope' field
    org_id = int(form_data.scopes[0]) if form_data.scopes else None
    if org_id is None:
        raise HTTPException(status_code=400, detail="Organization must be selected.")

    # Find the user within the specified organization
    query = users.select().where(
        users.c.username == form_data.username,
        users.c.organization_id == org_id
    )
    user_record = await database.fetch_one(query)

    if not user_record or not verify_password(form_data.password, user_record['hashed_password']):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password for this organization",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # ADD organization_id to the JWT token payload
    token_data = {"sub": user_record['username'], "org_id": org_id}
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data=token_data, expires_delta=access_token_expires
    )

    response.set_cookie(key="access_token", value=access_token, httponly=True, samesite="lax")
    return {"access_token": access_token, "token_type": "bearer"}

class UserCreate(BaseModel):
    organization_id: int
    username: str
    full_name: str
    email: str
    password: str
    role: str

@app.post("/register", status_code=status.HTTP_201_CREATED)
async def register_user(user: UserCreate):
    # Fetch the organization to validate the email domain
    org_query = organizations.select().where(organizations.c.id == user.organization_id)
    org = await database.fetch_one(org_query)
    if not org:
        raise HTTPException(status_code=400, detail="Invalid organization selected.")

    if not user.email.endswith(org.required_email_domain):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid email domain. Only @{org.required_email_domain} is allowed for this organization."
        )

    # Check for duplicate username within the same organization
    query = users.select().where(users.c.username == user.username, users.c.organization_id == user.organization_id)
    if await database.fetch_one(query):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered in this organization."
        )
    
    await create_user(user)
    return {"message": "User created successfully."}

@app.post("/api/labs", status_code=status.HTTP_201_CREATED)
async def create_lab(lab: LabCreate, current_user: User = Depends(get_current_active_user)):
    if current_user.role not in ["org_admin", "super_admin"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")
    query = labs.insert().values(**lab.dict(),organization_id=current_user.organization_id)
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
    system = MultiAgentTrafficSystem(current_user=current_user, manager=manager,org_id=current_user.organization_id)
    await system.initialize_system()

    await websocket.send_text(json.dumps({
        "type": "auth_success",
        "data": {"username": current_user.username, "role": current_user.role, "full_name": current_user.full_name}
    }))

    today = datetime.now(timezone.utc) 
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

                    now = datetime.now(timezone.utc)
                    start_of_week = now - timedelta(days=now.weekday())
                    end_of_week = start_of_week + timedelta(days=7)
                    updated_schedule = await system.get_schedule_for_range(start_of_week, end_of_week)
                    await manager.broadcast(json.dumps({"type":"schedule_update", "data": updated_schedule}))
                except Exception as e:
                    await websocket.send_text(json.dumps({"type":"error","data": str(e)}))

            elif message.get("type") == "get_full_schedule":
                full_schedule_data = system.get_full_schedule()
                await websocket.send_text(json.dumps({"type": "full_schedule_update", "data": full_schedule_data}))
            elif message.get("type") == "new_conversation":
                system.conversation_state = {}
                await websocket.send_text(json.dumps({"type": "log", "data": "New conversation started."}))

    except fastapi.WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        print(f"An unexpected error occurred in websocket: {e}")
        manager.disconnect(websocket)
    finally:
        manager.disconnect(websocket)


@app.on_event("startup")
async def startup():
    await database.connect()
    # This line creates all the tables defined in models.py.
    # It MUST be called before any queries are made.
    metadata.create_all(bind=engine)

    async with database.transaction():
        # Check if the 'System' organization for the super admin already exists
        system_org_query = organizations.select().where(organizations.c.name == "System")
        system_org = await database.fetch_one(system_org_query)
        
        # If it doesn't exist, create it along with the super admin user
        if not system_org:
            system_org_id = await database.execute(
                query=organizations.insert(),
                values={
                    "name": "System",
                    "required_email_domain": "system.local",
                    "owner_id": None # We'll update this after creating the admin
                }
            )
            
            admin_username = os.getenv("ADMIN_USERNAME", "admin")
            admin_user_values = {
                "organization_id": system_org_id,
                "username": admin_username,
                "full_name": "Platform Super Admin",
                "email": os.getenv("ADMIN_EMAIL", "admin@system.local"),
                "hashed_password": pwd_context.hash(os.getenv("ADMIN_PASSWORD", "admin123")),
                "role": "super_admin"
            }
            admin_id = await database.execute(query=users.insert(), values=admin_user_values)

            # Now, link the new admin as the owner of the 'System' organization
            await database.execute(
                query=organizations.update().where(organizations.c.id == system_org_id),
                values={"owner_id": admin_id}
            )

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

@app.post("/api/organizations/register", status_code=status.HTTP_201_CREATED)
async def register_organization(org_data: OrganizationCreate):
    # Check if organization name or domain already exists
    query = organizations.select().where(organizations.c.name == org_data.org_name)
    if await database.fetch_one(query):
        raise HTTPException(status_code=400, detail="Organization name already exists.")
    
    query = organizations.select().where(organizations.c.required_email_domain == org_data.email_domain)
    if await database.fetch_one(query):
        raise HTTPException(status_code=400, detail="Email domain is already in use by another organization.")

    # Validate that the admin's email matches the required domain
    if not org_data.admin_email.endswith(org_data.email_domain):
        raise HTTPException(status_code=400, detail=f"Admin email must use the @{org_data.email_domain} domain.")

    # Use a database transaction to ensure all or nothing
    async with database.transaction():
        # Step 1: Create the organization record first, but without an owner_id
        org_query = organizations.insert().values(
            name=org_data.org_name,
            required_email_domain=org_data.email_domain,
            owner_id=None # We will update this after creating the user
        )
        org_id = await database.execute(org_query)

        # Step 2: Create the admin user for this organization
        hashed_password = pwd_context.hash(org_data.admin_password)
        user_query = users.insert().values(
            organization_id=org_id,
            username=org_data.admin_username,
            full_name=org_data.admin_full_name,
            email=org_data.admin_email,
            hashed_password=hashed_password,
            role="org_admin" # Assign the new role
        )
        user_id = await database.execute(user_query)

        # Step 3: Now, update the organization with the new admin's user_id
        update_org_query = organizations.update().where(organizations.c.id == org_id).values(owner_id=user_id)
        await database.execute(update_org_query)

    return {"message": "Organization and admin account created successfully."}

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