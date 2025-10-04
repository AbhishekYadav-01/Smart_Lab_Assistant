# simulation.py
import asyncio
import json
from datetime import datetime, timedelta
import fastapi 
import sqlalchemy 
from auth import User 
from typing import Dict, List, Any, Optional
from agents import HeadLabAssistantAgent, LabAgent
from data_models import Booking 
from database import database
from models import users, labs, bookings

class MultiAgentTrafficSystem:
    """Main system orchestrating all agents"""

    def __init__(self, current_user: User, manager: 'ConnectionManager'):
        """
        Initializes the system for a specific, authenticated user.
        """
        self.current_user = current_user
        self.manager = manager 
        self.head_assistant_agent = HeadLabAssistantAgent() 
        self.lab_agents: List[LabAgent] = []
        self.agent_map: Dict[str, LabAgent] = {}

    async def broadcast_schedule_update(self):
        """Fetches the latest weekly schedule and broadcasts it to all clients."""
        today = datetime.now()
        start_of_week = today - timedelta(days=today.weekday())
        end_of_week = start_of_week + timedelta(days=7)
        schedule_data = await self.get_schedule_for_range(start_of_week, end_of_week)
        await self.manager.broadcast(json.dumps({"type": "schedule_update", "data": schedule_data}))

        
    async def get_full_schedule(self) -> dict:
            """Gathers all schedule data by querying the database."""
            today = datetime.now()
            start_of_week = today - timedelta(days=today.weekday())
            end_of_week = start_of_week + timedelta(days=7)
            return await self.get_schedule_for_range(start_of_week, end_of_week)
        
    
    # --- THIS IS THE MODIFIED METHOD ---
    async def handle_availability_query(self, query_text: str, websocket: fastapi.WebSocket):
        """
        Orchestrates the handling of a user's availability query with intelligent filtering.
        """
        async def send_update(msg_type, data):
            await websocket.send_text(json.dumps({"type": msg_type, "data": data}))

        try:
            await send_update("log", "Parsing your query with the Head Assistant Agent...")
            parsed_request = await self.head_assistant_agent.parse_user_query(query_text)
            
            if not parsed_request or not parsed_request.get("date") or not parsed_request.get("start_time"):
                await send_update("error", "Sorry, I could not understand the time and date from your request. Please be more specific.")
                return

            # Extract details from the parsed request
            student_count = parsed_request.get("student_count", 1)
            requested_lab_name = parsed_request.get("lab_name")
            requested_equipment = parsed_request.get("equipment")
            
            await send_update("log", f"Parsed Request: Looking for slots on {parsed_request['date']} from {parsed_request['start_time']} to {parsed_request['end_time']}.")
            
            try:
                date_str = parsed_request["date"]
                start_str = parsed_request["start_time"]
                end_str = parsed_request["end_time"]
                request_start = datetime.fromisoformat(f"{parsed_request['date']}T{parsed_request['start_time']}")
                request_end = datetime.fromisoformat(f"{parsed_request['date']}T{parsed_request['end_time']}")
            except (ValueError, KeyError):
                await send_update("error", "Invalid date/time format parsed. Please try again.")
                return

            # --- INTELLIGENT AGENT FILTERING LOGIC ---
            target_agents = self.lab_agents
            # 1. Highest Priority: Filter by specific lab name
            if requested_lab_name:
                await send_update("log", f"Searching specifically in {requested_lab_name}...")
                target_agents = [agent for agent in self.lab_agents if agent.lab_name.lower() == requested_lab_name.lower()]
            
            # 2. Second Priority: Filter by equipment
            elif requested_equipment:
                await send_update("log", f"Filtering for labs with: {', '.join(requested_equipment)}")
                
                # Build a database query to find labs matching the criteria
                search_conditions = [sqlalchemy.or_(labs.c.equipment.ilike(f"%{item}%"), labs.c.description.ilike(f"%{item}%")) for item in requested_equipment]
                
                matching_labs_query = labs.select().where(sqlalchemy.and_(*search_conditions))
                matching_lab_records = await database.fetch_all(matching_labs_query)
                matching_lab_names = {lab['name'] for lab in matching_lab_records}

                # Filter the agent list
                target_agents = [agent for agent in self.lab_agents if agent.lab_name in matching_lab_names]

                if not target_agents:
                    await send_update("log", "No labs found matching your specific criteria.")                    
                    await send_update("availability_results", []) # Send empty results
                    return
            
            await send_update("log", f"Broadcasting request to {len(target_agents)} relevant Lab Agent(s)...")
            tasks = []
            for agent in target_agents:
                lab_record = await database.fetch_one(labs.select().where(labs.c.name == agent.lab_name))
                bookings_query = bookings.select().where(bookings.c.lab_id == lab_record.id)
                current_schedule = await database.fetch_all(bookings_query)
                tasks.append(agent.check_availability(request_start, request_end, student_count, current_schedule))
            
            responses = await asyncio.gather(*tasks)
            
            results = []
            for i, response in enumerate(responses):
                results.append({
                    "lab_name": target_agents[i].lab_name,
                    "status": response["status"], 
                    "start_time": request_start.isoformat(), 
                    "end_time": request_end.isoformat(),
                    "student_count": student_count
                })
            await send_update("availability_results", results)

        except Exception as e:
            await send_update("error", f"An error occurred: {e}")

    async def get_schedule_for_range(self, start_date: datetime, end_date: datetime) -> dict:
        """Gathers schedule data for a specific date range by querying the database."""
        query = bookings.select().where(
            bookings.c.start_time >= start_date,
            bookings.c.start_time < end_date
        )
        all_bookings = await database.fetch_all(query)
        
        schedule_data = {agent.lab_name: [] for agent in self.lab_agents}
        
        for booking in all_bookings:
            lab_query = labs.select().where(labs.c.id == booking.lab_id)
            lab = await database.fetch_one(lab_query)
            if lab and lab.name in schedule_data:
                schedule_data[lab.name].append({
                    "id": booking.id,
                    "booked_by": booking.booked_by,
                    "start_time": booking.start_time.isoformat(),
                    "end_time": booking.end_time.isoformat(),
                    "student_count": booking.student_count,
                })
        return schedule_data

    async def handle_shift_request(self, data: dict, websocket: fastapi.WebSocket):
        async def send_update(msg_type, data):
            await websocket.send_text(json.dumps({"type": msg_type, "data": data}))

        lab_name = data['lab_name']
        target_agent = self.agent_map.get(f"LabAgent_{lab_name.replace(' ', '_')}")
        if not target_agent: return

        request_start = datetime.fromisoformat(data['start_time'])
        request_end = datetime.fromisoformat(data['end_time'])
        
        check_result = await target_agent.check_availability(request_start, request_end, 1)
        conflicting_booking = check_result.get("booking")
        if not conflicting_booking:
            await send_update("error", "Could not find the flexible booking to negotiate for.")
            return

        await send_update("log", f"Initiating negotiation with {target_agent.name}...")
        proposal = f"A user urgently needs the lab from {request_start.strftime('%I:%M %p')} to {request_end.strftime('%I:%M %p')}. Can you shift your booking for '{conflicting_booking.booked_by}'? In return, we will grant you a future priority booking (reputation increase)."
        
        requester_reputation = self.head_assistant_agent.reputation_scores.get(target_agent.name, 10)
        
        response = await target_agent.evaluate_proposal(proposal, conflicting_booking, requester_reputation)
        await send_update("log", f"[{target_agent.name} responded]: {response}")

        if response.strip().upper().startswith("ACCEPT"):
            shift_minutes = conflicting_booking.flexibility_minutes
            target_agent.shift_booking(conflicting_booking, shift_minutes)
            await send_update("log", f"✅ {target_agent.name} accepted! The slot is now available.")
            await self.handle_availability_query(f"check labs for {data['start_time']} to {data['end_time']}", websocket)
        
        elif response.strip().upper().startswith("COUNTER"):
            await send_update("log", f"🔵 {target_agent.name} made a counter-offer. For this demo, we will accept it.")
            shift_minutes = 15
            target_agent.shift_booking(conflicting_booking, shift_minutes)
            await send_update("log", f"✅ Counter-offer accepted! The slot should now be available.")
            await self.handle_availability_query(f"check labs for {data['start_time']} to {data['end_time']}", websocket)

        else: # REJECT
            await send_update("log", f"❌ {target_agent.name} rejected the request. The slot remains unavailable.")
            
    async def handle_booking_request(self, data: dict, websocket: fastapi.WebSocket):
        """Handles a booking request by writing to the database, checking roles and setting priority."""
        if self.current_user.role == 'student':
            await websocket.send_text(json.dumps({"type": "error", "data": "Permission Denied: Students cannot book labs."}))
            return

        lab_name = data['lab_name']
        start_time = datetime.fromisoformat(data['start_time'])
        end_time = datetime.fromisoformat(data['end_time'])
        student_count = data.get('student_count', 1)
        
        lab_record = await database.fetch_one(labs.select().where(labs.c.name == lab_name))
        user_record = await database.fetch_one(users.select().where(users.c.username == self.current_user.username))
        
        if lab_record and user_record:

            # --- CRITICAL: FINAL AVAILABILITY CHECK ---
            target_agent = self.agent_map.get(f"LabAgent_{lab_name.replace(' ', '_')}")
            if target_agent:
                # Get the most up-to-date schedule from DB right before booking
                latest_schedule_query = bookings.select().where(bookings.c.lab_id == lab_record.id)
                latest_schedule = await database.fetch_all(latest_schedule_query)
                
                availability = await target_agent.check_availability(start_time, end_time, student_count, latest_schedule)
# --- CRITICAL: FINAL AVAILABILITY CHECK (IMPROVED) ---
            if availability['status'] != 'AVAILABLE':
                error_msg = "Booking failed: The slot is no longer available." # Default message

                if availability['status'] == 'CONFLICT_CAPACITY':
                    # Fetch lab capacity to provide a specific error
                    lab_capacity = lab_record.capacity
                    error_msg = f"Booking failed: Student count ({student_count}) exceeds lab capacity of {lab_capacity}."

                elif availability['status'] == 'CONFLICT_RIGID':
                    owner = availability.get('owner', 'another user')
                    error_msg = f"Booking failed: Slot is booked by {owner}."
                    if owner == self.current_user.username:
                        error_msg = "Booking failed: You have already booked this lab for an overlapping time."

                await websocket.send_text(json.dumps({"type": "error", "data": error_msg}))
                return
            
            
            priority = 3 
            email_prefix = self.current_user.email.split('@')[0].upper()
            if email_prefix.startswith('P'):
                priority = 1
            elif email_prefix.startswith('B'):
                priority = 2
            
            query = bookings.insert().values(
                lab_id=lab_record.id,
                user_id=user_record.id,
                start_time=start_time,
                end_time=end_time,
                student_count=student_count,
                booked_by=self.current_user.username,
                priority=priority,
            )
            await database.execute(query)
            await websocket.send_text(json.dumps({"type": "booking_confirmation", "data": {"lab_name": lab_name}}))
            await self.broadcast_schedule_update()
            
        else:
            await websocket.send_text(json.dumps({"type": "error", "data": "Booking failed: Invalid lab or user."}))

    async def handle_cancellation_request(self, data: dict, websocket: fastapi.WebSocket):
        """Handles a user's request to cancel a booking."""
        lab_name = data['lab_name']
        start_time_str = data.get('start_time')
        booking_id = data.get('booking_id')

        agent_to_update = self.agent_map.get(f"LabAgent_{lab_name.replace(' ', '_')}")
        if not agent_to_update:
            await websocket.send_text(json.dumps({"type": "error", "data": "Invalid lab agent."}))
            return

        if booking_id:
            booking_record = await database.fetch_one(bookings.select().where(bookings.c.id == booking_id))
            if not booking_record:
                await websocket.send_text(json.dumps({"type": "error", "data": "Booking not found."}))
                return
            start_time = booking_record.start_time
        elif start_time_str:
             start_time = datetime.fromisoformat(start_time_str)
        else:
            await websocket.send_text(json.dumps({"type": "error", "data": "Booking identifier missing."}))
            return

        success, message = await agent_to_update.cancel_booking(start_time, self.current_user)
        
        if success:
            await websocket.send_text(json.dumps({"type": "log", "data": f"✅ Booking in {lab_name} successfully cancelled."}))
            await self.broadcast_schedule_update()
        else:
            await websocket.send_text(json.dumps({"type": "error", "data": message}))

    async def handle_student_count_update(self, data: dict, websocket: fastapi.WebSocket):
        """Handles updating the student count for a booking."""
        booking_id = data.get('booking_id')
        new_student_count = data.get('student_count')

        if not booking_id or new_student_count is None:
            await websocket.send_text(json.dumps({"type": "error", "data": "Invalid data for update."}))
            return

        booking_record = await database.fetch_one(bookings.select().where(bookings.c.id == booking_id))
        if not booking_record:
            await websocket.send_text(json.dumps({"type": "error", "data": "Booking not found."}))
            return

        is_owner = self.current_user.username == booking_record.booked_by
        is_admin = self.current_user.role == 'super_admin'

        if not (is_owner or is_admin):
            await websocket.send_text(json.dumps({"type": "error", "data": "Permission Denied: You cannot modify this booking."}))
            return

        lab_record = await database.fetch_one(labs.select().where(labs.c.id == booking_record.lab_id))
        if new_student_count > lab_record.capacity:
            await websocket.send_text(json.dumps({"type": "error", "data": f"Update failed: Exceeds lab capacity of {lab_record.capacity}."}))
            return

        query = bookings.update().where(bookings.c.id == booking_id).values(student_count=new_student_count)
        await database.execute(query)

        await websocket.send_text(json.dumps({"type": "log", "data": "✅ Student count updated."}))
        await self.broadcast_schedule_update()
                               
    async def initialize_system(self):
            """Asynchronously initializes labs and agents from the database."""
            lab_records = await database.fetch_all(query=labs.select())
            lab_names = [lab['name'] for lab in lab_records]
            lab_agent_names = [f"LabAgent_{name.replace(' ', '_')}" for name in lab_names]
            
            self.head_assistant_agent = HeadLabAssistantAgent(all_lab_agent_names=lab_agent_names)
            
            for lab in lab_records:
                agent = LabAgent(lab['name'], lab['capacity'], lab_agent_names)
                self.lab_agents.append(agent)
                self.agent_map[agent.name] = agent