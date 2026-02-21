# ai-audio-transcriber
An end-to-end, multi-agent pipeline that turns raw interview audio into structured qualitative insights.

# Instructions for setting up this project
- You will need to create a `.env` file at the project root and add the OpenAI API key to that file. More info can be found in the Readme contained at `professor_framework/README.md`

## Instructions for working on this project with Docker and VS Code
1. You'll need to have Docker installed. You can install [Docker Desktop](https://www.docker.com/products/docker-desktop/) or whatever other method you prefer. As students, I believe we should qualify for a Docker Personal license. 
2. You will need to install the "Dev Containers" extension for VS Code [here](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers).
3. Clone down the repository. 
4. Open the ai-audio-transcriber folder in VS Code. It should automatically give you a prompt saying that you can re-open the project in a dev container. If not, you can open the command palette (Ctrl+Shift+P on Windows) and search for "Dev Containers: Re-open in container". 
5. It will take a few minutes to set everything up the first time, but then you should be able to work on the project from within the container. 
    - If there are squiggles on the imports, try also opening the command palette and searching "Python: Select Interpreter" and selecting it, then choosing the version at `/usr/local/bin/python`. It should be version 3.12. 
6. If requirements are tweaked, it will probably become necessary to rebuild the container. You can do so with the command palette by searching for "Dev Containers: Rebuild Container Without Cache". 

### Other notes: 
- Ctrl+\` will let you open a terminal where you can run the relevant commands, such as `python agent.py agents.yaml`
- The environment should be set up such that if you place an audio file in your local `/audio` folder, it should become available within the container. This should help with testing. It should also be set up to ignore all files in that folder when committing so we don't try to commit large files.
- I was not able to test this on any other system so let me know if there are any issues. 
- If we ever needed to actually deploy the app on some kind of production server that uses docker containers, we might need to do some further tweaking. I didn't have any way to test that. I think that's probably outside of the scope of the class, though. 
- We will probably need to continue to tweak the requirements and Dockerfile as we learn more about the needs of the project.