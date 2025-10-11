import json
import re
from typing import Dict, List, Optional
from datetime import datetime, timedelta,timezone, time

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

    async def parse_user_query(self, query_text: str, history: Optional[Dict] = None) -> Optional[Dict]:
        """
        Parses a query, gathers all required details sequentially (including student count), 
        generates a final confirmation question, and understands user approval.
        """
        history_str = json.dumps(history) if history else "{}"
        conversation_status = history.get("status", "gathering_info")

        parsing_task = f"""
        You are a conversational AI lab assistant. Your goal is to gather all necessary information sequentially, confirm details, and understand user approval.

        - The current state of gathered information is: {history_str}
        - The current conversation status is: "{conversation_status}"
        - The user's latest message is: "{query_text}"
        - **IMPORTANT: If the user says "today", you MUST use the current date: {datetime.now(timezone.utc).strftime('%A, %Y-%m-%d')}.**

        Follow these steps based on the conversation status:

        1.  If status is "gathering_info":
            - Merge information from the user's message into the history.
            - **Your required information sequence is: `date`, `start_time`, `end_time`, `student_count`.**
            - If `date` is missing, ask for it.
            - If `date` is present but `start_time` is missing, ask for the start time.
            - If `start_time` is present but `end_time` is missing, ask for the end time.
            - **If `end_time` is present but `student_count` is missing, ask for the number of students.**
            - Once all four are present, change the status to "pending_confirmation".

        2.  If status is "pending_confirmation":
            - Analyze the user's message for intent.
            - If the intent is **approval** (e.g., "yes", "go ahead", "correct"), you MUST set `user_approved` to `true` and set `clarification_question` to `null`. This is critical to stop the loop.
            - If the intent is a **modification** (e.g., "change to 30 students"), update the details, remove `user_approved`, change status back to "gathering_info", and ask a new question if needed.

        - When the status becomes "pending_confirmation" for the first time, your `clarification_question` MUST be a full summary including the student count.
        Example: "Perfect! I have the following details: A booking for **30 students** on 2025-10-12 from 14:00 to 16:00. Shall I go ahead and check for availability?"

        - If you don't have a `student_count` yet, you can default it to 1 in your internal thought process, but you must still ask the user to confirm.

        Respond ONLY with a valid JSON object containing the full, updated state.
        """
        response = await self.agent.run(task=parsing_task)
        try:
            content = str(response.messages[-1].content)
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                json_str = json_match.group(0)
                return json.loads(json_str)
            return {"status": "gathering_info", "clarification_question": "I'm sorry, I had trouble understanding that. Could you please rephrase?"}
        except (json.JSONDecodeError, IndexError):
            return {"status": "gathering_info", "clarification_question": "I'm having a little trouble understanding. Could you tell me the date you need?"}
                
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


    async def check_availability(self, request_start: datetime, request_end: datetime, requested_student_count: int, current_schedule: list,operating_start: Optional[time] = None,operating_end: Optional[time] = None) -> dict:
        """Checks for conflicts against a provided schedule, now also checking capacity."""
        if self.capacity < requested_student_count:
            return {"status": "CONFLICT_CAPACITY", "owner": None, "booking": None}
        if request_start < datetime.now(timezone.utc):
            return {"status": "CONFLICT_PAST", "owner": None, "booking": None}

        if operating_start and operating_end:
            request_start_time = request_start.time()
            request_end_time = request_end.time()
            # Handle overnight bookings simply by checking start and end separately
            if not (operating_start <= request_start_time < operating_end and operating_start < request_end_time <= operating_end):
                return {"status": f"CONFLICT_HOURS: Lab is only open from {operating_start.strftime('%I:%M %p')} to {operating_end.strftime('%I:%M %p')}", "owner": None, "booking": None}

        for booking_data in current_schedule:
            booking_start = booking_data["start_time"]
            booking_end = booking_data["end_time"]
            
            if booking_start.tzinfo is None:
                booking_start = booking_start.replace(tzinfo=timezone.utc)
            if booking_end.tzinfo is None:
                booking_end = booking_end.replace(tzinfo=timezone.utc)

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
