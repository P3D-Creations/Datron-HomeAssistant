---
name: Datron M8Cube Homeassistant Setup
description: Initial project definition prompt
---

<!-- Tip: Use /create-prompt in chat to generate content with agent assistance -->

Format this folder as a github repository.
Keep a log of chat interactions in a file named `chat_log.md` in the root of the repository.
Keep critical projects notes and information for use with LLMS in a file named `project_notes.md` in the root of the repository.


I have a Datron M8Cube CNC milling machine with the NEXT control, running version 3.8x of the software. It has a restful API that I would like to use with Home Assistant. It has a swagger API documentation page so it is very easy to see all of the available information to get or post. The swagger page included the oas3.json file which is a standard format for describing RESTful APIs. I want to use this API to create a custom integration in Home Assistant that allows me to monitor and control my CNC machine from within the Home Assistant interface.

This should be using the V2 of the API unless there are specific features that are only available in V1. In the schema it appears you can specify which version of the API you want to use for each endpoint, so I will specify V2 for all endpoints unless there is a specific reason to use V1.

I'd like to be able to monitor virtually all of the exposed api endpoints. 
The critical ones are:
- Machine status (running, idle, error, etc.)
- Current job information (job name, progress, estimated time remaining, etc.)
- Control commands (start, stop, pause, resume, etc.)
- Error notifications (if the machine encounters an error, I want to be notified in Home Assistant)
- Maintenance alerts (if the machine requires maintenance, I want to be notified in Home Assistant)
- Sensor data (temperature, spindle speed, air pressure, vacuum pressure, coolant tank status etc.)
- Workpiece image

Nice to have:
- Camera access
- Preview image of the current job
- Tools in internal magazine
- Tools in warehouse

I have the basic API access right this moment which hides some information and also prevents control of most aspects of the machine. I intend to ask about the Automation API tier which will allow me to start, pause, stop the machine, and also administer programs. In the future I will want to have access to these additional features but presently they are not important unless the endpoint information is available in the oas3.json file.


I do not need: 
- Tools in tool assist
- Cartridge information (this is for the dispening variant which we do not have)

I already have:
- A bearer token for authentication with the API, which I will use in the Home Assistant integration to authenticate API requests. I don't know if it expires. If it does not then we can leave it static. if it does expire then we will need to implement a way to refresh the token in the Home Assistant integration.

The Home Assistant integration should be designed to be as efficient as possible, minimizing the number of API calls while still providing real-time updates on the machine's status and job information. I want to be able to see the machine's status and job information in the Home Assistant dashboard, and I want to be able to control the machine using buttons or other controls in the Home Assistant interface.
Information such as remaining time, running status, and error notifications should be updated in real-time or near real-time in the Home Assistant interface. Tool information should be update less frequently but still often so we can monitor for changes in measured length throughout the duration of a program or throughout the day. Administrative information such as the machine verion, software version, and other static information can be updated less frequently, perhaps once a day or when the integration is first set up. Axis positions and sensor data should be updated at the same rate as the machine status and job information, as these can change frequently during operation. 


Build the framework for the Home Assistant integration, including the necessary configuration files and code structure according to best practices for Home Assistant custom integrations. For the moment lets use standard icons and other home assistant graphical elements. Later on we can customize the icons and graphical elements. 

For starters I only need the entities exposed for the critical endpoints mentioned above. Once we have those working we can expand to include the nice-to-have features and any other endpoints that are available in the API. 

Eventually we can consider a custom card for CNC machines and possibly expand this to work with additional machinery from other brands, as long as I can get the status or control data into home assistant. 
