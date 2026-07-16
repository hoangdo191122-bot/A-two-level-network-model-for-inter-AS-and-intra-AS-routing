This file describes what the code files are about and instructs you on how to run the simulation:
- Description:
+ router.py, topology.py, models.py are the programs which generate the network topology along with all components inside it. These programs also contain the BGP routing policies, and Dijkstra's algorithm.
+ main.py is the program where you can run the simulation inside the terminal.
+ app.py is where you can run the simulation on a web server. Check the instructions below.

- How to run the simulation:
Step 1: Download all python files and the html file: main.py, models.py, router.py, topology.py, index.html.

Step 2: Create this directory tree:

main/
├── main.py
├── models.py
├── router.py
├── topology.py
└── template/
    └── index.html

Step 3: Run the app.py file: python3 app.py

Step 4: Open a web browser and go to the link: http://127.0.0.1:5000

- Download the jupyter notebook and open it to see the performance evaluations.
