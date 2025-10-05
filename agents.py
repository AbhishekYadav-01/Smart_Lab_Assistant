import json
import re
from typing import Dict, List, Optional
from datetime import datetime, timedelta, timezone
from starlette.concurrency import run_in_threadpool
from autogen_agentchat.agents import AssistantAgent
from auth import User 
from config import model_client
from data_models import Booking, Commitment
from database import *
from models import labs, bookings 


class HeadLabAssistantAgent:
    """The central agent that receives user queries and coordinates the Lab Agents."""

    def __init__(self, name="HeadLabAssistant", all_lab_agent_names: List[str] = []):
        self.name = name
        self.agent = AssistantAgent(
            name=name,
            model_client=model_client,
            system_message="""You are the Head Lab Assistant for IIT Jodhpur. Your primary role is to coordinate lab bookings.
            1. You will receive a natural language query from a user.
            2. Your first task is to parse this query to extract key details: the requested day, start time, end time, and any specific lab names, features, or equipment requested.
            3. You will then broadcast this structured request to all individual Lab Agents that match the criteria.
            4. You will collect the availability responses from all Lab Agents.
            5. Finally, you will aggregate these responses into a clear, single summary to be sent back to the user."""
        )
        self.reputation_scores = {name: 10 for name in all_lab_agent_names}

    async def parse_user_query(self, query_text: str) -> Optional[Dict]:
        """Uses an LLM to parse a natural language query into a structured dictionary."""
        
        parsing_task = f"""
        You are an expert at parsing user requests for lab bookings. Your task is to extract key details from a query.

        - The current date is {datetime.now(timezone.utc).strftime('%A, %Y-%m-%d')}.
        - If a specific lab name is mentioned (e.g., "AI Lab", "Robotics Lab"), extract it into a "lab_name" key.
        - If specific equipment or features are mentioned (e.g., "computers", "soldering iron"), extract them as a list in an "equipment" key.
        - If the number of students is not mentioned, default to 1.
        - The date must be in YYYY-MM-DD format and times in 24-hour format.

        Here are some examples:
        1. Query: "Is the AI Lab free next Tuesday afternoon for 20 people?"
           JSON: {{"date": "2025-10-07", "start_time": "13:00", "end_time": "17:00", "student_count": 20, "lab_name": "AI Lab"}}
        2. Query: "Is there a lab with a soldering iron available tomorrow morning?"
           JSON: {{"date": "2025-10-05", "start_time": "09:00", "end_time": "12:00", "student_count": 1, "equipment": ["soldering iron"]}}
        3. Query: "find a lab for 10 people on Monday from 2 to 4 PM"
           JSON: {{"date": "2025-10-06", "start_time": "14:00", "end_time": "16:00", "student_count": 10}}

        Now, parse the following query. Respond ONLY with a valid JSON object.
        QUERY: "{query_text}"
        """
        # response = await self.agent.run(task=parsing_task)
        try:
            response = await self.agent.run(task=parsing_task)
            content = str(response.messages[-1].content)
            json_str = content[content.find('{'):content.rfind('}')+1]
            return json.loads(json_str)
        except (json.JSONDecodeError, IndexError, AttributeError):
            print(f"[{self.name}] ERROR: Failed to parse user query.")
            return None

class LabAgent:
    def __init__(self, lab_name: str, capacity: int, all_agent_names: List[str]):
        self.lab_name = lab_name

        sanitized_name = re.sub(r'\W|^(?=\d)', '_', lab_name)
        self.name = f"LabAgent_{sanitized_name}"

        self.capacity = capacity
        self.agent = AssistantAgent(
            name=self.name, model_client=model_client,
            system_message=f"You are the assistant for {self.lab_name} with a capacity of {self.capacity} students. You manage its schedule. You must evaluate proposals to shift existing bookings based on their priority and your flexibility. You can ACCEPT, REJECT, or make a COUNTER-OFFER (e.g., 'I can only shift by 15 minutes')."
        )
        
        self.reputation_scores = {name: 10 for name in all_agent_names if name != self.name}


    async def check_availability(self, request_start: datetime, request_end: datetime, requested_student_count: int, current_schedule: list) -> dict:
        """Checks for conflicts against a provided schedule, now also checking capacity."""
        if self.capacity < requested_student_count:
            return {"status": "CONFLICT_CAPACITY", "owner": None, "booking": None}

        for booking_data in current_schedule:
            booking_start = booking_data["start_time"]
            booking_end = booking_data["end_time"]
            
            if (request_start < booking_end) and (request_end > booking_start):
                conflict_details = {
                    "status": "CONFLICT_RIGID", 
                    "owner": booking_data["booked_by"], 
                    "booking": booking_data
                }
                return conflict_details

        return {"status": "AVAILABLE", "owner": None, "booking": None}
    

    def add_booking(self, start_time: datetime, end_time: datetime, booked_by: str, student_count: int) -> bool:
        is_available = True
        for booking in self.schedule:
            if max(booking.start_time, start_time) < min(booking.end_time, end_time):
                is_available = False
                break
        if is_available and self.capacity >= student_count:
            self.schedule.append(Booking(booked_by=booked_by, start_time=start_time, end_time=end_time, student_count=student_count))
            return True
        return False
        
    def shift_booking(self, booking_to_shift: Booking, minutes: int) -> bool:
        booking_to_shift.start_time += timedelta(minutes=minutes)
        booking_to_shift.end_time += timedelta(minutes=minutes)
        return True

    async def evaluate_proposal(self, proposal: str, existing_booking: Booking, requester_reputation: int) -> str:
        evaluation_task = f"""
        You are the agent for {self.lab_name}.
        An existing booking is from {existing_booking.start_time.strftime('%I:%M %p')} to {existing_booking.end_time.strftime('%I:%M %p')} for {existing_booking.booked_by}.
        This booking has a flexibility of {existing_booking.flexibility_minutes} minutes.
        
        A request has come in from an agent with a reputation score of {requester_reputation}.
        The proposal is: '{proposal}'

        Based on the booking's flexibility and the requester's reputation, decide your response.
        - If the request is reasonable and reputation is good, you should ACCEPT.
        - If the request is unreasonable, you should REJECT.
        - If the request is possible but not ideal, make a COUNTER-OFFER (e.g., "I can only shift by 15 minutes, not 30.").
        
        Your response MUST start with ACCEPT, REJECT, or COUNTER.
        """
        response = await self.agent.run(task=evaluation_task)
        return str(response.messages[-1].content)

    async def cancel_booking(self, start_time: datetime, user_to_cancel: User) -> bool:
        lab_query = labs.select().where(labs.c.name == self.lab_name)
        lab_record = await database.fetch_one(lab_query)
        if not lab_record:
            return False, "Lab not found."

        booking_query = bookings.select().where(
            bookings.c.lab_id == lab_record.id,
            bookings.c.start_time == start_time
        )
        booking_to_remove = await database.fetch_one(booking_query)
        
        if booking_to_remove:
            is_owner = booking_to_remove.booked_by == user_to_cancel.username
            is_admin = user_to_cancel.role == 'super_admin'
            if is_owner or is_admin:
                delete_query = bookings.delete().where(bookings.c.id == booking_to_remove.id)
                await database.execute(delete_query)
                return True, "Booking cancelled successfully."
            else:
                error_msg = f"PERMISSION DENIED: {user_to_cancel.username} tried to cancel a booking owned by {booking_to_remove.booked_by}."
                print(error_msg)
                return False, error_msg
        return False, "Booking not found to cancel."
