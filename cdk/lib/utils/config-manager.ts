// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import * as fs from "fs"
import * as path from "path"
import * as yaml from "yaml"

const MAX_STACK_NAME_BASE_LENGTH = 35

export type DeploymentType = "docker" | "zip"

/**
 * Network mode for the AgentCore Runtime.
 * - PUBLIC: Runtime is accessible over the public internet (default).
 * - VPC: Runtime is deployed into a user-provided VPC for private network isolation.
 */
export type NetworkMode = "PUBLIC" | "VPC"

/**
 * VPC configuration for deploying the AgentCore Runtime into an existing VPC.
 * Required when network_mode is "VPC".
 */
export interface VpcConfig {
  /** The ID of the existing VPC to deploy into (e.g. "vpc-0abc1234def56789a"). */
  vpc_id: string
  /** List of subnet IDs within the VPC where the runtime will be placed. */
  subnet_ids: string[]
  /** Optional list of security group IDs. If omitted, a default security group is created. */
  security_group_ids?: string[]
}

/**
 * "Same sub" OBO federation: lets SAP Cloud Identity Services (IAS) consume the
 * product's user-facing Cognito pool as an OIDC corporate IdP, so a user-initiated
 * SAP MCP USER_FEDERATION call reaches SAP as the real human user. This is pure
 * IdP trust — it does NOT change any SAP MCP transport config. Anchored on the
 * user-facing pool (cognito-stack.ts), never the SAP MCP inbound pool.
 * See docs/sap/SAP_MCP_SAME_SUB_FEDERATION.md.
 */
export interface SapFederationConfig {
  /** When true, our CDK provisions the IAS-facing Cognito app client. Default false. */
  enabled?: boolean
  /** IAS callback/ACS URL registered as an allowed callback on the Cognito app client. */
  ias_redirect_uri?: string
  /** Claim used as the Cognito→IAS→S/4 join key. Default "email". */
  mapping_claim?: string
}

/**
 * Identity configuration for SAP-bound requests.
 *
 * Interactive user→SAP identity is handled by the external SAP MCP server's
 * USER_FEDERATION flow; the only knob retained here is the "same sub" OBO
 * federation that lets SAP IAS consume the user-facing Cognito pool.
 */
export interface SapIdentityConfig {
  /** "Same sub" OBO federation (Cognito → IAS corporate IdP). */
  federation?: SapFederationConfig
}

export interface NotificationConfig {
  channel?: "ses" | "servicenow" | "jira"
  /** SES sender email (ses channel) */
  ses_sender_email?: string
  /** Secrets Manager ARN for channel credentials (servicenow/jira) */
  secret_arn?: string
}

export interface AgentQueueConfig {
  /** Max concurrent agent invocations (SQS event source maxConcurrency). Default 5. */
  max_concurrency?: number
}

export interface AutonomyConfig {
  /** auto = poller enqueues immediately, manual = human triggers. Default manual. */
  trigger_mode?: "auto" | "manual"
}

export interface BatchConfig {
  /** EventBridge schedule for the `mode: batch` sweeper. Default rate(1 hour). */
  schedule?: string
}

/**
 * AWS for SAP MCP Server configuration.
 *
 * See ADR-012 and docs/sap/SAP_MCP_INTEGRATION.md. The SAP MCP integration is a
 * pure adapter: the AWS-published SAP MCP CloudFormation stack (external) owns
 * the runtime, its inbound Cognito/Entra pool, the outbound SAP OAuth provider,
 * and every SAP permission knob (reads vs writes are enabled there via the
 * runtime's `MCP_SERVER_*` env vars — see the AWS config reference). Our CDK
 * only mints Gateway targets pointed at it. Two target variants are supported:
 * `service` (machine identity to SAP) and `user` (interactive per-user OBO via
 * USER_FEDERATION); each is a simple on/off toggle.
 *
 * When `enabled: false` (default) no resources are created.
 */
export interface SapMcpConfig {
  /** Master switch. When false, sap-mcp-stack is not deployed. */
  enabled?: boolean

  /**
   * Reference to the AWS-published SAP MCP CloudFormation stack. The SAP MCP
   * integration is external-only: that stack owns the runtime, inbound Cognito
   * pool, and outbound OAuth provider; our CDK attaches a Gateway target +
   * Gateway OAuth2 provider pointed at it. Required whenever sap_mcp.enabled.
   */
  external_stack?: SapMcpExternalStackConfig

  /**
   * Gateway target listing mode.
   * - DEFAULT (the enforced default) pre-syncs the tool catalog and enables semantic search.
   * - DYNAMIC forwards tools/list at invoke time and is the safe fallback that
   *   avoids schema normalization when tool schemas don't normalize cleanly.
   */
  listing_mode?: "DYNAMIC" | "DEFAULT"

  // Note: the target variant (Service / User) is derived from auth_profile's
  // outbound axis at synth.
}

/**
 * Reference to an AWS-deployed SAP MCP CloudFormation stack (external/hybrid mode).
 * Outputs are auto-resolved at synth via CloudFormation describe-stacks; the
 * fields below override resolution when set.
 */
export interface SapMcpExternalStackConfig {
  /** Name of the AWS-published SAP MCP CFN stack to read outputs from. */
  stack_name: string
  /** Region of the external CFN stack. Defaults to the deploy region when unset. */
  region?: string
  /** Inbound IdP the external stack was deployed with. Must match its deploy. */
  inbound_auth_provider?: "Cognito" | "EntraId"
  /**
   * OAuth scopes the Gateway requests when minting the inbound token for the
   * external runtime. MUST be scopes the external IdP's resource server defines
   * — for the AWS-published SAP MCP stack this is
   * `awsforsap-mcp-m2m-resource-server-<UniqueId>/read` (and `/write`).
   * When unset, falls back to `<stack_name_base>-gateway/read` (only correct if
   * the external pool happens to share our gateway's resource server).
   */
  inbound_scopes?: string[]
  /** Override: MCP invocation URL (else resolved from the stack's Outputs). */
  invocation_url?: string
  /**
   * Optional allowlist of regex patterns the resolved MCP invocation URL MUST
   * match. A defense against a misconfigured or tampered external_stack pointing
   * the Gateway at an attacker-controlled endpoint (threat T13). When unset, only
   * the baseline https:// scheme check applies.
   */
  allowed_endpoint_patterns?: string[]
  /** Override: external stack's inbound Cognito details (else resolved). */
  inbound_cognito?: {
    pool_id?: string
    client_id?: string
    token_endpoint?: string
    /** ARN of a Secrets Manager secret holding the Cognito client secret. */
    client_secret_arn?: string
  }
  /**
   * EntraId inbound auth overrides (used when inbound_auth_provider is "EntraId").
   * The external stack's inbound authorizer validates Entra-issued tokens, so the
   * Gateway OAuth2 provider must use the Entra discovery URL + client instead of
   * the Cognito pool-derived values.
   */
  entra_discovery_url?: string
  entra_client_id?: string
  entra_client_secret_arn?: string
}


/**
 * Optional security hardening toggles. All default OFF so the sample deploys
 * cheaply; production deployments turn these on.
 */
export interface SecurityConfig {
  /** Attach a REGIONAL WAFv2 WebACL (rate-limit + AWS managed rules) to the API Gateway stage. Threats T1/T11. */
  waf_enabled?: boolean
  /** Create a Bedrock Guardrail and wire it into the agent's model. Threats T2/T15. */
  guardrail_enabled?: boolean
  /**
   * Create a CloudTrail trail feeding the autonomy-change alarm (M7).
   *
   * CloudTrail allows only 5 trails per Region and that is a hard limit, not a
   * raisable quota. Creating one unconditionally caps how many copies of this
   * sample can coexist in a Region and fails the deploy outright once the
   * account is at the limit, so it is opt-in.
   */
  audit_trail_enabled?: boolean
}

/**
 * Precedent retrieval + vendor risk traversal, backed by one Aurora Serverless
 * v2 cluster. Default OFF: with this block absent the stack provisions no
 * cluster, no VPC, and no tool, so the golden path's cost is unchanged.
 */
export interface AgentKnowledgeConfig {
  /** Provision the cluster, schema, and Gateway tool. Default false. */
  enabled?: boolean
  /**
   * Aurora Serverless v2 minimum ACUs. 0 lets the cluster auto-pause to ~$0
   * idle at the cost of a ~15s resume on the first call after a pause. 0.5
   * (~$43/mo in us-east-1) removes the stall. Default 0.
   */
  min_acu?: number
  /** Idle seconds before auto-pause. RDS accepts 300–86400. Default 3600. */
  seconds_until_auto_pause?: number
  /** Vendor node/edge tables and the check_vendor_risk tool. Default true. */
  vendor_risk?: boolean
}

export interface AppConfig {
  stack_name_base: string
  admin_user_email?: string | null
  backend: {
    pattern: string
    deployment_type: DeploymentType
    /** Network mode for the AgentCore Runtime. Defaults to "PUBLIC". */
    network_mode: NetworkMode
    /** VPC configuration. Required when network_mode is "VPC". */
    vpc?: VpcConfig
  }
  notification?: NotificationConfig
  agent_queue?: AgentQueueConfig
  autonomy?: AutonomyConfig
  batch?: BatchConfig
  cedar_enforcement_mode?: "LOG_ONLY" | "ENFORCE"
  security?: SecurityConfig
  demo?: {
    /** Backwards-compat sugar: true enables both ticketing and test_data. */
    enabled?: boolean
    /** Ticketing/ITSM stand-in: tickets table, /tickets API, ticket Gateway tool. */
    ticketing?: { enabled?: boolean }
    /** Test-data generation: DemoStack, demo_test_data lambda, example_* skills. */
    test_data?: { enabled?: boolean }
  }
  contacts?: Record<string, string>
  alarm_email?: string
  /**
   * Knowledge Base (vector) tuning. Governs how SOP documents are chunked when
   * ingested into the SOPs Bedrock KB that backs the `search_sap_sops` tool.
   */
  knowledge_base?: {
    /**
     * Chunking strategy for the SOPs vector KB:
     *  - "BEDROCK_DEFAULT": omit explicit chunking configuration. This preserves
     *    legacy data sources created before chunking became config-driven and
     *    lets Bedrock select its default for newly created data sources.
     *  - "NONE" (default): one vector per SOP file → whole-SOP retrieval, never
     *    fragments mixed across SOPs. Requires each SOP to fit the embedding
     *    input limit (Titan v2 ≈ 8k tokens / 50k chars).
     *  - "FIXED_SIZE": ~maxTokens chunks with overlap. For long SOPs that exceed
     *    the embedding limit. Combine with SOP-scoped metadata for integrity.
     *  - "SEMANTIC": structure-aware chunks. Best for long, well-sectioned SOPs.
     */
    sops_chunking_strategy?: "BEDROCK_DEFAULT" | "NONE" | "FIXED_SIZE" | "SEMANTIC"
    /** FIXED_SIZE/SEMANTIC: target max tokens per chunk (default 300). */
    sops_chunk_max_tokens?: number
    /** FIXED_SIZE: overlap percentage between adjacent chunks, 1–99 (default 20). */
    sops_chunk_overlap_percentage?: number
  }
  agent_knowledge?: AgentKnowledgeConfig
  sap?: {
    base_url?: string
    identity?: SapIdentityConfig
    ses_sender_email?: string | null
    poller_schedule?: string
    embedding_model?: string
  }
  sap_mcp?: SapMcpConfig
}

export class ConfigManager {
  private config: AppConfig

  constructor(configFile: string) {
    this.config = this._loadConfig(configFile)
  }

  private _loadConfig(configFile: string): AppConfig {
    let configPath = path.join(__dirname, "..", "..", configFile) // nosemgrep: path-join-resolve-traversal

    if (!fs.existsSync(configPath)) { // nosemgrep: detect-non-literal-fs-filename
      const examplePath = configPath + ".example"
      if (fs.existsSync(examplePath)) { // nosemgrep: detect-non-literal-fs-filename
        console.warn(`config.yaml not found — falling back to ${examplePath} (CI/synth-check mode)`)
        configPath = examplePath
      } else {
        throw new Error(`Configuration file ${configPath} does not exist. Please create config.yaml file.`)
      }
    }

    try {
      const fileContent = fs.readFileSync(configPath, "utf8") // nosemgrep: detect-non-literal-fs-filename
      const parsedConfig = yaml.parse(fileContent) as AppConfig

      const deploymentType = parsedConfig.backend?.deployment_type || "docker"
      if (deploymentType !== "docker" && deploymentType !== "zip") {
        throw new Error(`Invalid deployment_type '${deploymentType}'. Must be 'docker' or 'zip'.`)
      }

      const stackNameBase = parsedConfig.stack_name_base
      if (!stackNameBase) {
        throw new Error("stack_name_base is required in config.yaml")
      }
      if (stackNameBase.length > MAX_STACK_NAME_BASE_LENGTH) {
        throw new Error(
          `stack_name_base '${stackNameBase}' is too long (${stackNameBase.length} chars). ` +
            `Maximum length is ${MAX_STACK_NAME_BASE_LENGTH} characters due to AWS AgentCore runtime naming constraints.`
        )
      }
      if (stackNameBase.includes("_")) {
        throw new Error(
          `stack_name_base '${stackNameBase}' contains underscores. ` +
            `Use hyphens instead (e.g. 'my-project' not 'my_project'). ` +
            `Underscores cause failures in AWS resource naming (S3 buckets, Cognito, etc.).`
        )
      }

      const networkMode = parsedConfig.backend?.network_mode || "PUBLIC"
      if (networkMode !== "PUBLIC" && networkMode !== "VPC") {
        throw new Error(`Invalid network_mode '${networkMode}'. Must be 'PUBLIC' or 'VPC'.`)
      }

      const sopsChunkingStrategy = parsedConfig.knowledge_base?.sops_chunking_strategy || "NONE"
      if (!["BEDROCK_DEFAULT", "NONE", "FIXED_SIZE", "SEMANTIC"].includes(sopsChunkingStrategy)) {
        throw new Error(
          `Invalid knowledge_base.sops_chunking_strategy '${sopsChunkingStrategy}'. ` +
            `Must be 'BEDROCK_DEFAULT', 'NONE', 'FIXED_SIZE', or 'SEMANTIC'.`
        )
      }

      const vpcConfig = parsedConfig.backend?.vpc
      if (networkMode === "VPC") {
        if (!vpcConfig) {
          throw new Error("backend.vpc configuration is required when network_mode is 'VPC'.")
        }
        if (!vpcConfig.vpc_id) {
          throw new Error("backend.vpc.vpc_id is required when network_mode is 'VPC'.")
        }
        if (!vpcConfig.subnet_ids || vpcConfig.subnet_ids.length === 0) {
          throw new Error("backend.vpc.subnet_ids must contain at least one subnet ID when network_mode is 'VPC'.")
        }
      }

      return {
        stack_name_base: stackNameBase,
        admin_user_email: parsedConfig.admin_user_email || null,
        backend: {
          pattern: parsedConfig.backend?.pattern || "agent",
          deployment_type: deploymentType,
          network_mode: networkMode,
          vpc: vpcConfig,
        },
        notification: parsedConfig.notification ? {
          channel: parsedConfig.notification.channel || "ses",
          ses_sender_email: parsedConfig.notification.ses_sender_email,
          secret_arn: parsedConfig.notification.secret_arn,
        } : undefined,
        agent_queue: parsedConfig.agent_queue ? {
          max_concurrency: parsedConfig.agent_queue.max_concurrency || 5,
        } : undefined,
        contacts: parsedConfig.contacts,
        knowledge_base: {
          sops_chunking_strategy: sopsChunkingStrategy as "BEDROCK_DEFAULT" | "NONE" | "FIXED_SIZE" | "SEMANTIC",
          sops_chunk_max_tokens: parsedConfig.knowledge_base?.sops_chunk_max_tokens ?? 300,
          sops_chunk_overlap_percentage: parsedConfig.knowledge_base?.sops_chunk_overlap_percentage ?? 20,
        },
        autonomy: {
          trigger_mode: parsedConfig.autonomy?.trigger_mode || "manual",
        },
        batch: parsedConfig.batch ? {
          schedule: parsedConfig.batch.schedule,
        } : undefined,
        sap: parsedConfig.sap ? {
          base_url: parsedConfig.sap.base_url,
          identity: this._normalizeSapIdentity(parsedConfig.sap.identity),
          ses_sender_email: parsedConfig.sap.ses_sender_email || null,
          poller_schedule: parsedConfig.sap.poller_schedule || "rate(5 minutes)",
          embedding_model: parsedConfig.sap.embedding_model || "amazon.titan-embed-text-v2:0",
        } : undefined,
        sap_mcp: this._normalizeSapMcpConfig(parsedConfig.sap_mcp),
        security: {
          waf_enabled: parsedConfig.security?.waf_enabled === true,
          guardrail_enabled: parsedConfig.security?.guardrail_enabled === true,
          audit_trail_enabled: parsedConfig.security?.audit_trail_enabled === true,
        },
        demo: this._normalizeDemo(parsedConfig.demo),
        agent_knowledge: this._normalizeAgentKnowledge(parsedConfig.agent_knowledge),
      }
    } catch (error) {
      throw new Error(`Failed to parse configuration file ${configPath}: ${error}`)
    }
  }

  public getProps(): AppConfig {
    return this.config
  }

  public get(key: string, defaultValue?: any): any {
    const keys = key.split(".")
    let value: any = this.config

    for (const k of keys) {
      // nosemgrep: prototype-pollution-loop — already using hasOwnProperty guard
      if (typeof value === "object" && value !== null && Object.prototype.hasOwnProperty.call(value, k)) {
        value = value[k]
      } else {
        return defaultValue
      }
    }

    return value
  }

  /**
   * Normalize the demo block into two independent sub-flags. `demo.enabled: true`
   * is backwards-compat sugar that enables both. Returns undefined when neither
   * ticketing nor test_data is on, so downstream `config.demo?.` checks stay simple.
   */
  private _normalizeDemo(
    raw?: AppConfig["demo"]
  ): AppConfig["demo"] | undefined {
    if (!raw) {
      return undefined
    }
    const ticketing = raw.enabled === true || raw.ticketing?.enabled === true
    const testData = raw.enabled === true || raw.test_data?.enabled === true
    if (!ticketing && !testData) {
      return undefined
    }
    return {
      enabled: ticketing && testData,
      ticketing: { enabled: ticketing },
      test_data: { enabled: testData },
    }
  }

  /**
   * Collapse the agent_knowledge block to undefined unless explicitly enabled,
   * so `if (config.agent_knowledge?.enabled)` is the only gate any caller needs.
   */
  private _normalizeAgentKnowledge(
    raw: AgentKnowledgeConfig | undefined,
  ): AgentKnowledgeConfig | undefined {
    if (raw?.enabled !== true) return undefined

    const autoPause = raw.seconds_until_auto_pause ?? 3600
    // RDS rejects anything outside this window; failing at synth beats failing
    // 20 minutes into a cluster deploy.
    if (autoPause < 300 || autoPause > 86400) {
      throw new Error(
        `agent_knowledge.seconds_until_auto_pause must be between 300 and 86400 (got ${autoPause})`,
      )
    }

    return {
      enabled: true,
      min_acu: raw.min_acu ?? 0,
      seconds_until_auto_pause: autoPause,
      vendor_risk: raw.vendor_risk ?? true,
    }
  }

  /**
   * Normalize and validate the sap.identity block. Currently this only covers
   * the "same sub" federation sub-block: when federation.enabled, ias_redirect_uri
   * is required and mapping_claim defaults to "email".
   */
  private _normalizeSapIdentity(
    raw?: SapIdentityConfig
  ): SapIdentityConfig | undefined {
    if (!raw) {
      return undefined
    }
    const fed = raw.federation
    if (fed?.enabled === true) {
      if (!fed.ias_redirect_uri) {
        throw new Error(
          "sap.identity.federation.ias_redirect_uri is required when " +
            "sap.identity.federation.enabled is true."
        )
      }
      return {
        ...raw,
        federation: {
          enabled: true,
          ias_redirect_uri: fed.ias_redirect_uri,
          mapping_claim: fed.mapping_claim || "email",
        },
      }
    }
    return raw
  }

  /**
   * Normalize and validate the sap_mcp config block.
   *
   * Returns undefined when sap_mcp is absent or disabled. Otherwise applies
   * sensible defaults and throws on obviously invalid inputs.
   */
  private _normalizeSapMcpConfig(raw?: SapMcpConfig): SapMcpConfig | undefined {
    if (!raw || raw.enabled !== true) {
      return undefined
    }

    // External-only: the AWS-published SAP MCP CFN stack owns the runtime,
    // inbound pool, and outbound OAuth provider. Our CDK is an adapter, so an
    // external_stack reference is always required.
    if (!raw.external_stack?.stack_name) {
      throw new Error(
        "sap_mcp.external_stack.stack_name is required (the SAP MCP integration is external-only)."
      )
    }
    const idp = raw.external_stack.inbound_auth_provider || "Cognito"
    if (idp !== "Cognito" && idp !== "EntraId") {
      throw new Error(
        `Invalid sap_mcp.external_stack.inbound_auth_provider '${idp}'. Must be 'Cognito' or 'EntraId'.`
      )
    }

    const listingMode = raw.listing_mode || "DEFAULT"
    if (listingMode !== "DYNAMIC" && listingMode !== "DEFAULT") {
      throw new Error(`Invalid sap_mcp.listing_mode '${listingMode}'. Must be 'DYNAMIC' or 'DEFAULT'.`)
    }

    // The active target variant (Service / User) is derived from auth_profile's
    // outbound axis at synth (see sap-mcp-stack.ts resolveOutboundProfile).
    return {
      enabled: true,
      external_stack: raw.external_stack,
      listing_mode: listingMode,
    }
  }
}
