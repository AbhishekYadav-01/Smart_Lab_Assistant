from databases import Database
from sqlalchemy import create_engine, MetaData
import os
from dotenv import load_dotenv

load_dotenv() 

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./lab_assistant.db")

database = Database(DATABASE_URL)
metadata = MetaData()
engine = create_engine(DATABASE_URL)