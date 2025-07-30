# 🚁 EchoPilot: A Voice-Controlled Drone Agent

Ever wanted to talk to your drone like you're in a sci-fi movie? EchoPilot makes it happen. This open-source project bridges the gap between natural language and autonomous flight, allowing you to command a drone simply by speaking.

At its core, EchoPilot uses a powerful, local Large Language Model (LLM) to automatically generate complex mission plans from a single voice command. Unlike solutions relying on external APIs, EchoPilot processes your commands right on your system, offering enhanced privacy and control. These plans are then executed by a robust set of tools running as a background service, communicating via the Model Context Protocol (MCP).


## ✨ Features

-   **Natural Language Control:** Command the drone with complex sentences like, "takeoff, fly to the Eiffel tower, orbit it, and then return to launch."
-   **Automatic Mission Planning:** The LLM acts as an intelligent flight officer, automatically creating a safe and logical sequence of tool calls based on your voice command.
-   **Decoupled Tool Server:** Drone capabilities run as an independent **MCP Server** in the background, making the system modular and easy to extend.
-   **Local & Offline First:** Designed to run primarily with a local LLM via **Ollama** and offline Text-to-Speech (`pyttsx3`), giving you full control without constant internet access.
-   **Telemetry-Verified Execution:** This isn't fire-and-forget. The drone's tools use real-time telemetry to confirm actions are physically complete—it waits for the drone to *actually arrive* at a location before proceeding.
-   **Safe by Design:** The **Planner-Executor** model ensures predictable behavior. The agent generates a full plan, which can be reviewed before the drone ever takes off.

## 🛠️ Architecture: The Brain-Hand-Voice Model

This project's power comes from its decoupled, three-part architecture, connected by the **Multi-Server Control Protocol (MCP)**.

```
+--------------------------+           +-----------------------------+
|    Drone Agent (Brain)   |           |    Tool Server (Hands)      |
|      (drone_agent.py)    |           |     (drone_server.py)       |
|--------------------------|           |-----------------------------|
| - Listens for Voice      |           | - Runs as a background      |
| - Uses LLM to create     |--(MCP)--> |   process (MCP Server)      |
|   a JSON mission plan    |           | - Exposes tools like        |
|   (a sequence of tools)  |           |   'fly_to_coordinates'      |
| - Executes plan step by  |           | - Talks to drone via MAVSDK |
|   step                   |           | - Verifies actions w/ telemetry |
+--------------------------+           +-----------------------------+
```

1.  **The Agent (The Brain 🧠):** The `drone_agent.py` script is the mission commander. It takes your voice command and uses the LLM to generate a mission plan. This plan is a structured list of which tools to call with which arguments.

2.  **The Tool Server (The Hands 👐):** The `drone_server.py` script is the real workhorse. It runs as an independent background process, acting as an **MCP Server**. It exposes the drone's physical capabilities (takeoff, land, fly) as a set of robust tools. The Agent dynamically discovers and calls these tools using MCP.

3.  **The Voice Interface (The Voice 🗣️):** The `speaker.py` and `voice_recognizer.py` modules provide a simple, offline interface for you to talk to the agent and for the agent to talk back to you.

## ⚙️ Setup Guide

Follow these steps to get the full EchoPilot experience up and running. This guide is tailored for **Ubuntu Linux**.

### Part 1: Setting up the PX4 Simulator (SITL)
This is the most involved part, but you only have to do it once.

1.  **Clone PX4 Autopilot:** The PX4 project is a git repository with many submodules. It's important to clone it recursively.
    ```bash
    git clone [https://github.com/PX4/PX4-Autopilot.git](https://github.com/PX4/PX4-Autopilot.git) --recursive
    ```

2.  **Run the Setup Script:** The PX4 team provides a fantastic script that installs all dependencies, including the Gazebo simulator.
    ```bash
    cd PX4-Autopilot
    bash ./Tools/setup/ubuntu.sh
    ```
    This script will ask for your password (`sudo`) and will take a while to run.

3.  **Build the Simulator:** The first build compiles everything. Grab a coffee, as this can take 10-20 minutes.
    ```bash
    make make px4_sitl gz_x500

    ```
    If successful, a Gazebo 3D window will launch with a drone on a runway. You can close it for now with `Ctrl+C`.

### Part 2: Setting up the EchoPilot Agent

1.  **Clone This Repository:**
    ```bash
    git clone [https://github.com/your-username/EchoPilot.git](https://github.com/Bilalileri/EchoPilot.git)
    cd EchoPilot
    ```

2.  **Install `uv` (Recommended Python Package Manager):**
    This project uses `uv` for fast and reliable dependency management.
    ```bash
    curl -LsSf [https://astral.sh/uv/install.sh](https://astral.sh/uv/install.sh) | sh
    source $HOME/.cargo/env
    ```

3.  **Create and Activate a Python Virtual Environment:**
    You can use `uv` to create and activate the environment in one step.
    ```bash
    # This will create a .venv folder based on the python version in .python-version
    uv venv
    source .venv/bin/activate
    ```
    You should see `(.venv)` at the start of your terminal prompt.

4.  **Install Python Packages:**
    Using `uv sync` will install the exact versions from `uv.lock`, ensuring a perfect setup.
    ```bash
    uv sync
    ```
    *(Alternative with pip: If you prefer not to use uv, you can still use pip with `pip install -r requirements.txt`, but `uv sync` is the recommended method for this project.)*
    ```

5.  **Configure Your LLM:**
    This project runs best with a local LLM via Ollama.

    1.  **Install Ollama:** Follow the instructions on the [official Ollama website](https://ollama.com/).
    2.  **Pull a Model:** We recommend Llama 3.
        ```bash
        ollama pull llama3
        ```
    3.  **Set the Code:** In `drone_agent.py`, make sure the `ChatOllama` line is active:
        ```python
        # LLM = init_chat_model("groq:llama3-8b-8192")
        LLM = ChatOllama(model="llama3.1")
        ```
    **Alternative (Fast Cloud LLM with Groq):**
    1.  Get a free API key from the [Groq Console](https://console.groq.com/keys).
    2.  Create a file named `.env` in the project root.
    3.  Add your key to the `.env` file: `GROQ_API_KEY="your_groq_api_key_here"`
    4.  In `drone_agent.py`, make sure the `init_chat_model` line is active:
        ```python
        LLM = init_chat_model("groq:llama3-8b-8192")
        # LLM = ChatOllama(model="llama3")
        ```
## ▶️ Running the Project


Running this project requires a specific startup sequence across multiple terminals.

### Step 1: Start the Core Services
First, launch the necessary background services for ROS 2 communication and the simulation.


* **Terminal #1: PX4 SITL Simulation**
    This command starts the drone simulation itself within Gazebo. The environment variables set the specific drone model and its starting position.
    ```bash
    cd ~/PX4-Autopilot
    PX4_SYS_AUTOSTART=4002 PX4_GZ_MODEL_POSE="268.08,-128.22,3.86,0.00,0,-0.7" PX4_GZ_MODEL=x500_depth ./build/px4_sitl_default/bin/px4
    ```
    Wait for the Gazebo window to appear and the PX4 console to finish its startup sequence.
    ``

### Step 2: Start the EchoPilot Agent
This is the final step that brings everything together.

* **Terminal #2: EchoPilot Agent**
    This runs the main voice-controlled agent. Make sure to activate your project's virtual environment first.
    ```bash
    source ~/echodrone/.venv/bin/activate  # Or your project's venv path
    cd ~/echodrone # Or your project's path
    python3 drone_agent.py
    ```

### Step 4: Give Your Command
* The agent will initialize and greet you.
* When prompted, speak your command clearly into your microphone.
* Watch the agent generate the plan in Terminal #5 and monitor the drone's execution in Gazebo!

---
#### (Optional) Monitor with QGroundControl
For a professional mission control dashboard, you can also run QGroundControl. It will automatically connect to the running simulation and give you a real-time map, telemetry, and a direct view into the drone's state.
```bash
# In another terminal, from where you downloaded it:
chmod +x ./QGroundControl.AppImage
./QGroundControl.AppImage
```

4.  **Give Your Command:**
    * The agent will initialize and greet you.
    * When prompted, speak your command clearly into your microphone.
    * Watch the agent generate the plan in the terminal and monitor the drone's execution in QGroundControl and Gazebo!

#### Example Commands
* "Takeoff, fly 50 meters forward, and then land."
* "Takeoff and go to the Eiffel Tower and come back."
* "Takeoff, fly to Pont d'Iéna bridge in Paris, orbit it, and then land there."
