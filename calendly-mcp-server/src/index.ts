#!/usr/bin/env node
import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { CallToolRequestSchema, ListToolsRequestSchema } from '@modelcontextprotocol/sdk/types.js';

import { CalendlyConfig, EmailConfig } from './types.js';
import { CalendlyClient } from './calendly-client.js';
import { EmailClient } from './email-client.js';
import { OAuthTools } from './tools/oauth-tools.js';
import { ApiTools } from './tools/api-tools.js';
import { EmailTools } from './tools/email-tools.js';
import { oauthToolDefinitions, apiToolDefinitions, emailToolDefinitions } from './tools/tool-definitions.js';

class CalendlyMCPServer {
  private server: Server;
  private config: CalendlyConfig;
  private client: CalendlyClient;
  private emailClient?: EmailClient;
  private oauthTools: OAuthTools;
  private apiTools: ApiTools;
  private emailTools?: EmailTools;

  constructor() {
    this.config = {
      apiKey: process.env.CALENDLY_API_KEY,
      accessToken: process.env.CALENDLY_ACCESS_TOKEN,
      refreshToken: process.env.CALENDLY_REFRESH_TOKEN,
      clientId: process.env.CALENDLY_CLIENT_ID,
      clientSecret: process.env.CALENDLY_CLIENT_SECRET,
      baseUrl: 'https://api.calendly.com',
      authUrl: 'https://auth.calendly.com',
      userUri: process.env.CALENDLY_USER_URI,
      organizationUri: process.env.CALENDLY_ORGANIZATION_URI,
      email: this.setupEmailConfig()
    };

    this.client = new CalendlyClient(this.config);
    this.oauthTools = new OAuthTools(this.client);
    this.apiTools = new ApiTools(this.client);
    
    // Initialize email client if email configuration is available
    if (this.config.email) {
      this.emailClient = new EmailClient(this.config.email);
      this.emailTools = new EmailTools(this.emailClient, this.client);
    }

    this.server = new Server(
      {
        name: 'calendly-mcp-server',
        version: '1.0.0',
      },
      {
        capabilities: {
          tools: {},
        },
      }
    );

    this.setupToolHandlers();
  }

  private setupEmailConfig(): EmailConfig | undefined {
    // Check for email configuration
    const provider = process.env.EMAIL_PROVIDER as 'sendgrid' | 'resend' | 'nodemailer' | undefined;
    const fromEmail = process.env.FROM_EMAIL;
    const fromName = process.env.FROM_NAME || 'Calendly MCP Server';

    if (!provider || !fromEmail) {
      console.error('Email configuration not found. Email features will be disabled.');
      console.error('To enable email features, set: EMAIL_PROVIDER, FROM_EMAIL, FROM_NAME');
      return undefined;
    }

    const config: EmailConfig = {
      provider,
      fromEmail,
      fromName
    };

    // Provider-specific configuration
    switch (provider) {
      case 'sendgrid':
        config.apiKey = process.env.SENDGRID_API_KEY;
        if (!config.apiKey) {
          console.error('SENDGRID_API_KEY environment variable is required for SendGrid');
          return undefined;
        }
        break;

      case 'resend':
        config.apiKey = process.env.RESEND_API_KEY;
        if (!config.apiKey) {
          console.error('RESEND_API_KEY environment variable is required for Resend');
          return undefined;
        }
        break;

      case 'nodemailer':
        const smtpHost = process.env.SMTP_HOST;
        const smtpUser = process.env.SMTP_USER;
        const smtpPass = process.env.SMTP_PASS;
        const smtpPort = parseInt(process.env.SMTP_PORT || '587');
        const smtpSecure = process.env.SMTP_SECURE === 'true';

        if (!smtpHost || !smtpUser || !smtpPass) {
          console.error('SMTP configuration incomplete. Required: SMTP_HOST, SMTP_USER, SMTP_PASS');
          return undefined;
        }

        config.smtpConfig = {
          host: smtpHost,
          port: smtpPort,
          secure: smtpSecure,
          auth: {
            user: smtpUser,
            pass: smtpPass
          }
        };
        break;

      default:
        console.error(`Unsupported email provider: ${provider}`);
        return undefined;
    }

    console.error(`Email configured with ${provider} provider`);
    return config;
  }

  private setupToolHandlers() {
    this.server.setRequestHandler(ListToolsRequestSchema, async () => {
      return {
        tools: [
          ...oauthToolDefinitions,
          ...apiToolDefinitions,
          ...(this.emailTools ? emailToolDefinitions : []),
        ],
      };
    });

    this.server.setRequestHandler(CallToolRequestSchema, async (request) => {
      const { name, arguments: args } = request.params;

      try {
        let result;
        switch (name) {
          // OAuth Tools
          case 'get_oauth_url':
            result = await this.oauthTools.getOAuthUrl(args?.redirect_uri as string, args?.state as string);
            break;
          case 'exchange_code_for_tokens':
            result = await this.oauthTools.exchangeCodeForTokens(args?.code as string, args?.redirect_uri as string);
            break;
          case 'refresh_access_token':
            result = await this.oauthTools.refreshAccessToken(args?.refresh_token as string);
            break;
          
          // API Tools
          case 'get_current_user':
            result = await this.apiTools.getCurrentUser();
            break;
          case 'list_events':
            result = await this.apiTools.listEvents(args);
            break;
          case 'get_event':
            result = await this.apiTools.getEvent(args?.event_uuid as string);
            break;
          case 'list_event_invitees':
            result = await this.apiTools.listEventInvitees(args?.event_uuid as string, args);
            break;
          case 'cancel_event':
            result = await this.apiTools.cancelEvent(args?.event_uuid as string, args?.reason as string);
            break;
          case 'get_event_type': {
            // Accept either event_type_uuid or legacy event_uuid key
            const rawArgs = args as any;
            const eventTypeUuid = rawArgs.event_type_uuid || rawArgs.event_uuid;
            if (!eventTypeUuid) {
              throw new Error('Missing event_type_uuid for get_event_type');
            }
            result = await this.apiTools.getEventType({ event_type_uuid: eventTypeUuid });
            break;
          }
          case 'create_one_off_event_type':
            result = await this.apiTools.createOneOffEventType(args as any);
            break;
          case 'list_organization_memberships':
            result = await this.apiTools.listOrganizationMemberships(args);
            break;
          
          // Email Tools
          case 'send_booking_invitation':
            if (!this.emailTools) {
              throw new Error('Email functionality not configured. Please set up email environment variables.');
            }
            result = await this.emailTools.sendBookingInvitation(args as any);
            break;
          case 'create_and_invite_workflow':
            if (!this.emailTools) {
              throw new Error('Email functionality not configured. Please set up email environment variables.');
            }
            result = await this.emailTools.createAndInviteWorkflow(args as any);
            break;
          
          default:
            throw new Error(`Unknown tool: ${name}`);
        }
        
        return result;
      } catch (error) {
        throw new Error(`Calendly API error: ${error}`);
      }
    });
  }

  async run() {
    const transport = new StdioServerTransport();
    await this.server.connect(transport);
    console.error('Calendly MCP server running on stdio');
  }
}

const server = new CalendlyMCPServer();
server.run().catch(console.error);