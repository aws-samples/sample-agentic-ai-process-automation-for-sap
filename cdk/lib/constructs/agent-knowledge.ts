// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import * as cdk from "aws-cdk-lib"
import * as ec2 from "aws-cdk-lib/aws-ec2"
import * as rds from "aws-cdk-lib/aws-rds"
import * as lambda from "aws-cdk-lib/aws-lambda"
import * as logs from "aws-cdk-lib/aws-logs"
import * as iam from "aws-cdk-lib/aws-iam"
import * as cr from "aws-cdk-lib/custom-resources"
import { Construct } from "constructs"
import { AppConfig } from "../utils/config-manager"
import * as path from "path"
import * as fs from "fs"
import * as crypto from "crypto"

export interface AgentKnowledgeProps {
  config: AppConfig
  /**
   * Shared Lambda layer carrying `amount_band`. queries.py imports it, and both
   * Lambdas here import queries.py — without the layer they fail at cold start
   * with ModuleNotFoundError.
   */
  sharedTypesLayer: lambda.ILayerVersion
}

const DATABASE_NAME = "agentknowledge"

function hashFile(file: string): string {
  return crypto.createHash("sha256").update(fs.readFileSync(file)).digest("hex").slice(0, 16)
}

/**
 * Precedent retrieval + vendor risk edges on one Aurora Serverless v2 cluster.
 *
 * Only instantiated when config.agent_knowledge.enabled — the caller gates it,
 * so a default deployment provisions nothing here.
 *
 * The cluster needs a VPC (rds.DatabaseCluster has no VPC-less mode), but the
 * Lambdas do not: they reach it over the RDS Data API, an HTTPS + IAM endpoint.
 * The VPC therefore has isolated subnets and no NAT gateway, so it costs nothing
 * while idle.
 */
export class AgentKnowledge extends Construct {
  public readonly toolFunction: lambda.Function
  public readonly cluster: rds.DatabaseCluster

  constructor(scope: Construct, id: string, props: AgentKnowledgeProps) {
    super(scope, id)

    const { config, sharedTypesLayer } = props
    const settings = config.agent_knowledge ?? {}
    const minAcu = settings.min_acu ?? 0
    const autoPauseSeconds = settings.seconds_until_auto_pause ?? 3600

    const vpc = new ec2.Vpc(this, "Vpc", {
      maxAzs: 2,
      natGateways: 0,
      subnetConfiguration: [
        { name: "isolated", subnetType: ec2.SubnetType.PRIVATE_ISOLATED, cidrMask: 24 },
      ],
    })

    this.cluster = new rds.DatabaseCluster(this, "Cluster", {
      engine: rds.DatabaseClusterEngine.auroraPostgres({
        version: rds.AuroraPostgresEngineVersion.VER_16_13,
      }),
      // ponytail: pinned minor. Keep this aligned with the deployed cluster;
      // Aurora PostgreSQL does not support in-place engine downgrades.
      // aws-cdk-lib ^2.262.1 also exposes VER_17_7 for a planned major upgrade.
      writer: rds.ClusterInstance.serverlessV2("writer"),
      serverlessV2MinCapacity: minAcu,
      serverlessV2MaxCapacity: 4,
      ...(minAcu === 0
        ? { serverlessV2AutoPauseDuration: cdk.Duration.seconds(autoPauseSeconds) }
        : {}),
      vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_ISOLATED },
      defaultDatabaseName: DATABASE_NAME,
      enableDataApi: true,
      // Aurora encrypts new clusters by default; stated explicitly so a
      // compliance scan reads it off the template instead of the AWS default.
      storageEncrypted: true,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    })

    const secret = this.cluster.secret
    if (!secret) {
      throw new Error("Aurora cluster did not mint a credentials secret")
    }

    const dataApiEnv = {
      CLUSTER_ARN: this.cluster.clusterArn,
      SECRET_ARN: secret.secretArn,
      DATABASE_NAME,
    }

    // Both Lambdas ship from the same directory so queries.py — the single
    // source for the DDL and the read queries — has exactly one copy. Each zip
    // therefore also carries the other's handler: a few KB of dead weight, and
    // the alternative (two directories) means two copies of the DDL.
    const toolDir = path.join(__dirname, "../../../agentcore/gateway/tools/agent_knowledge")

    const schemaLambda = new lambda.Function(this, "SchemaLambda", {
      runtime: lambda.Runtime.PYTHON_3_13,
      architecture: lambda.Architecture.ARM_64,
      handler: "schema_cr.handler",
      code: lambda.Code.fromAsset(toolDir),
      layers: [sharedTypesLayer],
      timeout: cdk.Duration.minutes(5),
      environment: dataApiEnv,
      logGroup: new logs.LogGroup(this, "SchemaLogGroup", {
        logGroupName: `/aws/lambda/${config.stack_name_base}-ak-schema`,
        retention: logs.RetentionDays.ONE_WEEK,
        removalPolicy: cdk.RemovalPolicy.DESTROY,
      }),
    })

    this.grantExecuteStatement(schemaLambda)
    secret.grantRead(schemaLambda)

    const schemaProvider = new cr.Provider(this, "SchemaProvider", {
      onEventHandler: schemaLambda,
    })
    // Hash of the DDL source, not a hand-bumped version: CloudFormation only
    // re-invokes a custom resource when its properties change, so a constant
    // here would leave new tables unapplied after a queries.py edit.
    const schema = new cdk.CustomResource(this, "Schema", {
      serviceToken: schemaProvider.serviceToken,
      properties: { SchemaHash: hashFile(path.join(toolDir, "queries.py")) },
    })
    schema.node.addDependency(this.cluster)

    this.toolFunction = new lambda.Function(this, "ToolLambda", {
      runtime: lambda.Runtime.PYTHON_3_13,
      architecture: lambda.Architecture.ARM_64,
      handler: "agent_knowledge_lambda.handler",
      code: lambda.Code.fromAsset(toolDir),
      layers: [sharedTypesLayer],
      timeout: cdk.Duration.seconds(30),
      environment: dataApiEnv,
      logGroup: new logs.LogGroup(this, "ToolLogGroup", {
        logGroupName: `/aws/lambda/${config.stack_name_base}-agent-knowledge`,
        retention: logs.RetentionDays.ONE_WEEK,
        removalPolicy: cdk.RemovalPolicy.DESTROY,
      }),
    })

    this.grantExecuteStatement(this.toolFunction)
    secret.grantRead(this.toolFunction)
    this.toolFunction.node.addDependency(schema)

    new cdk.CfnOutput(this, "ClusterArn", {
      value: this.cluster.clusterArn,
      description: "Agent knowledge Aurora cluster ARN",
    })
  }

  /**
   * Data API access narrowed to one action.
   *
   * cluster.grantDataApiAccess would also grant BatchExecuteStatement and the
   * three transaction actions. Nothing here batches or transacts, and the tool
   * Lambda is read-only, so the extra actions would only widen the blast radius.
   */
  private grantExecuteStatement(fn: lambda.Function): void {
    fn.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ["rds-data:ExecuteStatement"],
        resources: [this.cluster.clusterArn],
      }),
    )
  }

  /**
   * Let the exemplar builder upsert precedent rows.
   *
   * Same single-action grant as the read path — the upsert is one statement, so
   * it needs no batch or transaction actions either. Write capability comes from
   * the SQL, not from a wider IAM action set.
   */
  public grantPrecedentWrite(fn: lambda.Function): void {
    this.grantExecuteStatement(fn)
    this.cluster.secret!.grantRead(fn)
    fn.addEnvironment("CLUSTER_ARN", this.cluster.clusterArn)
    fn.addEnvironment("SECRET_ARN", this.cluster.secret!.secretArn)
    fn.addEnvironment("DATABASE_NAME", DATABASE_NAME)
  }
}
