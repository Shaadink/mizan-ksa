// Ask MIZAN agent endpoint (Azure Function in the owner's Azure subscription, UAE North). Not a secret: the Function
// holds no keys (managed identity to Azure OpenAI), accepts only this app's origin and is rate limited.
export const AGENT_URL = "https://func-mizan-agent-41a4ca.azurewebsites.net/api/ask";
export const AGENT_MODEL = "Azure OpenAI gpt-4.1-mini";
