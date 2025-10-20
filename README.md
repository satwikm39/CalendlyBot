# Calendly Scheduling Chatbot

A intelligent chatbot powered by LangGraph and FastAPI that integrates with Calendly through the Model Context Protocol (MCP). This bot uses the locally installed [calendly-mcp-server](https://github.com/meAmitPatil/calendly-mcp-server) to provide natural language scheduling capabilities.

## Features

- 🤖 **Natural Language Processing**: Ask questions about your Calendly schedule in plain English
- 📅 **Event Management**: List events, get event details, manage invitees, and cancel events
- 👥 **Organization Management**: List organization memberships and user information
- 📧 **Email Integration**: Send professional booking invitations (via SendGrid, Resend, or SMTP)
- 🔄 **Complete Workflows**: Create event types and automatically send invitations
- 🧠 **AI-Powered**: Uses Azure OpenAI for intelligent query understanding and response generation
- 🚀 **Serverless Ready**: Deployable to Vercel with zero configuration

## Architecture

This chatbot follows the WorkForceManagement pattern:

```
calendly-bot/
├── server.py                    # FastAPI application
├── CalendlyWorkflow.py          # LangGraph workflow with state management
├── MCP_Agent.py                 # MCP client wrapper
├── BaseSchema.py                # Shared state definitions
├── requirements.txt             # Python dependencies
├── vercel.json                  # Vercel deployment config
├── api/
│   └── index.py                 # Vercel serverless entrypoint
├── calendly-mcp-server/         # Local Calendly MCP server
│   ├── dist/                    # Compiled TypeScript
│   ├── src/                     # TypeScript source
│   └── package.json
└── env.example                  # Environment variables template
```

## Prerequisites

- **Python 3.9+** with `med` virtual environment
- **Node.js 18+** (for calendly-mcp-server)
- **Calendly Account** with API access
- **Azure OpenAI** (optional, for enhanced responses)

## Setup Instructions

### 1. Clone and Setup the Calendly MCP Server

The calendly-mcp-server is already included in the `calendly-bot` folder. Build it:

```bash
cd calendly-bot/calendly-mcp-server
npm install
npm run build
```

This will create the `dist/` folder with compiled JavaScript.

### 2. Create Python Virtual Environment

```bash
cd /Users/satwik/Developer/hgs/code/calendly-bot
python3 -m venv med
source med/bin/activate  # On Windows: med\Scripts\activate
```

### 3. Install Python Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables

Copy the example environment file:

```bash
cp env.example .env
```

Edit `.env` with your credentials:

```env
# Required: Calendly API credentials
CALENDLY_API_KEY=your_actual_api_key
CALENDLY_USER_URI=https://api.calendly.com/users/YOUR_USER_ID
CALENDLY_ORGANIZATION_URI=https://api.calendly.com/organizations/YOUR_ORG_ID

# Path to local MCP server (default works if unchanged)
CALENDLY_MCP_PATH=./calendly-mcp-server

# Optional: Azure OpenAI for enhanced responses
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_API_KEY=your_azure_key
AZURE_OPENAI_DEPLOYMENT=gpt-4o-mini
OPENAI_API_VERSION=2023-12-01-preview
```

### 5. Get Your Calendly API Credentials

1. Go to [Calendly Integrations](https://calendly.com/integrations/api_webhooks)
2. Generate a Personal Access Token
3. For OAuth flow, create an OAuth app and get Client ID/Secret
4. Get your User URI by calling: `GET https://api.calendly.com/users/me`
5. Get your Organization URI from the user response

## Running the Chatbot

### Local Development

```bash
# Activate virtual environment
source med/bin/activate

# Run the FastAPI server
uvicorn server:app --reload --port 8000
```

The API will be available at `http://localhost:8000`

### Test the API

```bash
# Health check
curl http://localhost:8000/health

# Ask a question
curl -X POST http://localhost:8000/calendly/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "Show me my upcoming events"}'
```

### CLI Mode (Direct Testing)

You can also run the workflow directly from the command line:

```bash
python CalendlyWorkflow.py "What events do I have this week?"
```

Options:
- `--debug`: Enable verbose logging
- `--visualize`: Display the workflow graph in ASCII

## Available Actions

The chatbot understands natural language queries and maps them to Calendly operations:

### View Information
- "Show me my upcoming events"
- "What events do I have today?"
- "Get details for event [UUID]"
- "Who is invited to my meeting?"
- "Show my organization memberships"

### Manage Events
- "Cancel my meeting with [event_uuid]"
- "Cancel event [UUID] because schedule changed"

### Send Invitations
- "Send a booking invitation to john@example.com for a 30-minute call"
- "Create a consultation event and invite sarah@company.com"
- "Schedule a meeting for Fridays and send invitation to team@startup.com"

## API Endpoints

### `POST /calendly/ask`

Main endpoint for natural language queries.

**Request:**
```json
{
  "question": "Show me my events for next week"
}
```

**Response:**
```json
{
  "answer": "You have 3 events scheduled next week:\n1. Client Meeting on Monday at 2 PM...\n2. Team Sync on Wednesday at 10 AM...\n3. Product Demo on Friday at 3 PM..."
}
```

### `GET /health`

Health check endpoint showing service status.

## Workflow Details

The LangGraph workflow consists of 4 nodes:

1. **cache_tools**: Fetches available Calendly MCP tools on first run
2. **classify**: Uses LLM to understand user intent and create action plan
3. **execute**: Calls the appropriate Calendly MCP tool with parameters
4. **respond**: Generates a user-friendly response from the results

```
[cache_tools] → [classify] → [execute] → [respond] → [END]
```

## Deployment to Vercel

1. Install Vercel CLI:
```bash
npm i -g vercel
```

2. Deploy:
```bash
cd /Users/satwik/Developer/hgs/code/calendly-bot
vercel
```

3. Set environment variables in Vercel dashboard:
   - Go to your project settings
   - Add all variables from `.env`
   - Redeploy

## Troubleshooting

### MCP Server Not Starting

**Issue**: `Failed to connect to Calendly MCP server`

**Solutions**:
- Verify Node.js 18+ is installed: `node --version`
- Check if MCP server was built: `ls calendly-mcp-server/dist/`
- Rebuild if needed: `cd calendly-mcp-server && npm run build`
- Check `CALENDLY_MCP_PATH` in `.env`

### Authentication Errors

**Issue**: `401 Unauthorized` or `No authentication token available`

**Solutions**:
- Verify `CALENDLY_API_KEY` is set correctly
- Test your API key: `curl -H "Authorization: Bearer $CALENDLY_API_KEY" https://api.calendly.com/users/me`
- Regenerate your Personal Access Token if expired

### Missing User URI

**Issue**: `400 errors on list_events` or `user_uri required`

**Solutions**:
- Set `CALENDLY_USER_URI` in `.env`
- Get it via: `curl -H "Authorization: Bearer $CALENDLY_API_KEY" https://api.calendly.com/users/me`
- Copy the `uri` field from the response

### Python Import Errors

**Issue**: `ModuleNotFoundError`

**Solutions**:
- Activate virtual environment: `source med/bin/activate`
- Install dependencies: `pip install -r requirements.txt`
- Verify Python version: `python --version` (should be 3.9+)

### LLM Not Available

The chatbot works without an LLM but responses will be raw JSON. For natural language responses, configure Azure OpenAI in `.env`.

## Development

### Adding New Tools

1. Add the tool to calendly-mcp-server (if not already available)
2. Update the `classify_question` prompt in `CalendlyWorkflow.py`
3. The workflow will automatically handle the new tool

### Modifying Response Format

Edit the `generate_response` function in `CalendlyWorkflow.py` to customize how responses are formatted.

### Custom Workflows

Create additional workflow nodes by:
1. Adding new node functions to `CalendlyWorkflow.py`
2. Registering them in `build_calendly_graph()`
3. Defining routing logic with `add_edge` or `add_conditional_edges`

## Contributing

This chatbot is based on the WorkForceManagement pattern. When contributing:
1. Follow the existing code structure
2. Use specific exception handling (never bare `except`)
3. Add logging for debugging
4. Update this README with any new features

## License

MIT License - see the calendly-mcp-server repository for details.

## Related Projects

- [calendly-mcp-server](https://github.com/meAmitPatil/calendly-mcp-server) - The MCP server this chatbot uses
- [WorkForceManagement](../WorkForceManagement) - The reference pattern for this implementation
- [LangGraph](https://github.com/langchain-ai/langgraph) - The workflow orchestration framework

## Support

For issues:
- **Calendly API**: [Calendly Developer Portal](https://developer.calendly.com/)
- **MCP Server**: [GitHub Issues](https://github.com/meAmitPatil/calendly-mcp-server/issues)
- **This Chatbot**: Contact your development team

---

Built with ❤️ using LangGraph, FastAPI, and the Model Context Protocol

