# Smart_Lab_Assistant: The Intelligent Lab Scheduler

### A Multi-Agent System for Smart Laboratory Booking

**Smart_Lab_Assistant** is a modern, real-time web application designed to solve the challenges of laboratory management at academic institutions like IIT Jodhpur. It replaces cumbersome manual booking processes with an intelligent, conversational interface powered by a sophisticated multi-agent system.

The system allows students and faculty to check lab availability, view schedules, and book resources using natural language. Behind the scenes, a team of autonomous software agents collaborates to understand requests, check constraints, and manage bookings, ensuring an efficient and conflict-free scheduling experience.

-----

## Table of Contents

  * [About The Project](https://www.google.com/search?q=%23about-the-project)
  * [Live Demo](https://www.google.com/search?q=%23live-demo)
  * [Core Features](https://www.google.com/search?q=%23core-features)
  * [System Architecture](https://www.google.com/search?q=%23system-architecture)
  * [Technology Stack](https://www.google.com/search?q=%23technology-stack)
  * [Getting Started](https://www.google.com/search?q=%23getting-started)
      * [Prerequisites](https://www.google.com/search?q=%23prerequisites)
      * [Local Installation](https://www.google.com/search?q=%23local-installation)
  * [Usage Guide](https://www.google.com/search?q=%23usage-guide)
      * [User Roles](https://www.google.com/search?q=%23user-roles)
  * [Deployment](https://www.google.com/search?q=%23deployment)
  * [Future Work](https://www.google.com/search?q=%23future-work)

-----

## About The Project

This project was born from a real-world challenge at IIT Jodhpur: the difficulty in knowing lab availability and the tedious process of manually checking schedules to book a slot. Smart_Lab_Assistant addresses this by creating a centralized, intelligent platform.

The core of this project is the implementation of a **Multi-Agent System (MAS)**. Instead of a monolithic backend, the system is composed of autonomous agents: a central `HeadLabAssistantAgent` that communicates with users and several `LabAgent`s, each representing a physical laboratory. This architecture allows for advanced features like intelligent search, and lays the groundwork for complex agent negotiations and social learning in the future.

-----

## Live Demo


A live version of this project is deployed on Render. You can access it here:

**https://smart-lab-assistant.onrender.com**

-----

## Core Features

Smart_Lab_Assistant is packed with features designed for administrators, teachers, and students.

### For All Users:

  * **Real-Time Dashboard**: A dynamic dashboard that updates instantly for all users via WebSockets.
  * **Intelligent Search**: Ask for labs in plain English (e.g., *"Is there a lab with a Raspberry Pi free tomorrow morning?"*). The system understands and filters results accordingly.
  * **Voice-Activated Queries**: Use your voice to ask for lab availability.
  * **Weekly Schedule View**: A beautiful, interactive grid showing all bookings for all labs for the current week.
  * **Functional Profile Page**: Users can view their profile details, change their password, and export their information as a vCard.
  * **Dark Mode**: A sleek, modern interface with a toggle for a dark theme.

### For Teachers:

  * **Lab Booking**: Teachers can book available lab slots directly from the search results or a manual booking form.
  * **Booking Management**: Teachers can edit the student count or cancel bookings they have made.
  * **Priority System**: Bookings are automatically prioritized based on the student group (PhD \> B.Tech \> M.Tech), determined from the teacher's email.

### For the Super Admin:

  * **Comprehensive Admin Panel**: A secure, dedicated dashboard for managing the entire system.
  * **Full User Management**: The admin can **add** and **delete** both students and teachers.
  * **Full Lab Management**: The admin has complete control to **create**, **update**, and **delete** labs, including details like capacity, description, and available equipment.
  * **Global Booking Control**: The admin can view and **delete any booking** made by any user in the system.

-----

## System Architecture

The application is built on a robust, modern architecture designed for real-time interaction and intelligent decision-making.

1.  **Frontend (Client)**: A dynamic single-page application built with HTML, JavaScript, and Bootstrap. It communicates with the backend exclusively through a persistent **WebSocket** connection.
2.  **Backend (FastAPI Server)**: A high-performance Python server that serves the frontend, handles user authentication, and manages the WebSocket connections.
3.  **Multi-Agent System (MAS)**: The brain of the application.
      * **`HeadLabAssistantAgent`**: The central coordinator. It receives natural language queries from users, uses a Large Language Model (LLM) to parse them into structured data, and filters the relevant lab agents.
      * **`LabAgent`s**: Each lab is represented by an agent. These agents manage their own schedules by interacting with the database and respond to availability requests from the head agent.
4.  **Database (PostgreSQL)**: A cloud-based PostgreSQL database that acts as the persistent memory for the entire system, storing all user, lab, and booking information.

-----

## Technology Stack

  * **Backend**: Python, FastAPI, Uvicorn
  * **Real-Time Communication**: WebSockets
  * **Multi-Agent System**: `autogen-agentchat`
  * **Database**: PostgreSQL, SQLAlchemy, `databases` library
  * **Authentication**: JWT (JSON Web Tokens), `passlib` for hashing
  * **Frontend**: HTML5, CSS3, JavaScript, Bootstrap 5
  * **Deployment**: Render

-----

## Getting Started

Follow these instructions to set up and run the project on your local machine.

### Prerequisites

  * Python 3.11+
  * A package manager like `pip`
  * A [Google Gemini API Key](https://aistudio.google.com/app/apikey) for the agent's natural language understanding.

### Local Installation

1.  **Clone the repository:**

    ```bash
    git clone [Your Repository URL]
    cd mas_visualization
    ```

2.  **Create and activate a virtual environment:**

      * On Windows:
        ```bash
        python -m venv .venv
        .venv\Scripts\activate
        ```
      * On macOS/Linux:
        ```bash
        python3 -m venv .venv
        source .venv/bin/activate
        ```

3.  **Install the dependencies:**

    ```bash
    pip install -r requirements.txt
    ```

4.  **Set up your Environment Variables:**

      * Create a file named `.env` in the `mas_visualization` directory.
      * Copy and paste the following content into it, replacing the placeholder values with your own secrets.

    <!-- end list -->

    ```env
    # .env file

    # LLM API Key
    GEMINI_API_KEY="AIzaSy...Your...Key...Here"

    # JWT Authentication Secrets
    SECRET_KEY="a_very_long_random_and_secret_string_for_security"
    ALGORITHM="HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES=30

    # Default Super Admin Credentials (used on first run)
    ADMIN_USERNAME=" "
    ADMIN_EMAIL=""
    ADMIN_PASSWORD=""

    # For local development, we use SQLite. Leave this blank.
    # DATABASE_URL=
    ```

5.  **Run the application:**

    ```bash
    uvicorn main:app --reload
    ```

6.  **Access the application:** Open your browser and navigate to `http://127.0.0.1:8000`.

-----

## Usage Guide

Once the application is running, you can interact with it through different roles.

### User Roles

  * **Super Admin**:

      * Log in with the credentials you set in your `.env` file (`admin`/`admin123` by default).
      * Access the **Admin Panel** from the user dropdown to manage all users, labs, and bookings.
      * Has all the permissions of a Teacher.

  * **Teacher**:

      * Register for an account with a valid `@iitj.ac.in` email and select the "Teacher" role.
      * Can use the "Ask for Availability" feature or the "Manual Booking" form to find and book labs.
      * Can edit the student count or cancel bookings they have personally made.

  * **Student**:

      * Register with a valid `@iitj.ac.in` email and select the "Student" role.
      * Can view the dashboard, check lab schedules, and use the search functionality.
      * Cannot book labs or see booking controls.

-----

## Deployment

This project is configured for easy deployment on **Render**.

1.  **Create a PostgreSQL database** on Render and copy the "Internal Database URL".
2.  **Create a Web Service** on Render and connect it to your GitHub repository.
3.  **Configure the service** with the following settings:
      * **Root Directory**: `mas_visualization`
      * **Build Command**: `pip install -r requirements.txt`
      * **Start Command**: `uvicorn main:app --host 0.0.0.0 --port 10000 --workers 1`
4.  **Add all the variables** from your `.env` file (including the `DATABASE_URL` from Render) to the "Environment Variables" section in your Render service settings.
5.  Deploy\! Render will automatically build and launch your application.
