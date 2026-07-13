// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import * as cdk from "aws-cdk-lib"
import * as ec2 from "aws-cdk-lib/aws-ec2"
import * as lambda from "aws-cdk-lib/aws-lambda"
import * as ssm from "aws-cdk-lib/aws-ssm"
import { pythonAssetCode } from "../utils/python-bundling"
import { Construct } from "constructs"
import type { AppConfig } from "../utils/config-manager"
import * as path from "path"

/**
 * SAP connectivity construct — reference-only networking + shared auth layer.
 *
 * Stores SAP connection metadata in SSM. Does NOT create networking resources.
 * When backend.network_mode is VPC, imports the customer's VPC/subnets/SG so
 * the OData poller can be placed in the VPC to reach private SAP endpoints.
 * Non-SAP Lambdas stay in public networking.
 *
 * Creates the shared sap_auth Lambda layer (service-account credential fetch +
 * error sanitization) for the poller. Interactive agent SAP access goes through
 * the external AWS-for-SAP MCP server, so machine identity here is
 * service-account only.
 */
export class SapConnectivity extends Construct {
  public readonly sapAuthLayer: lambda.ILayerVersion
  /** VPC config for SAP-facing Lambdas. Undefined when network_mode is PUBLIC. */
  public readonly vpc?: ec2.IVpc
  public readonly vpcSubnets?: ec2.SubnetSelection
  public readonly securityGroups?: ec2.ISecurityGroup[]
  private readonly sapBaseUrl: string
  private readonly stackNameBase: string

  constructor(scope: Construct, id: string, config: AppConfig) {
    super(scope, id)

    this.stackNameBase = config.stack_name_base
    this.sapBaseUrl = config.sap?.base_url || "https://localhost"

    // Import customer VPC when in VPC mode (for SAP-facing Lambdas)
    if (config.backend.network_mode === "VPC" && config.backend.vpc) {
      const vpcConfig = config.backend.vpc
      this.vpc = ec2.Vpc.fromLookup(this, "SapVpc", { vpcId: vpcConfig.vpc_id })
      this.vpcSubnets = {
        subnets: vpcConfig.subnet_ids.map(
          (id, i) => ec2.Subnet.fromSubnetId(this, `SapSubnet${i}`, id)
        ),
      }
      if (vpcConfig.security_group_ids?.length) {
        this.securityGroups = vpcConfig.security_group_ids.map(
          (id, i) => ec2.SecurityGroup.fromSecurityGroupId(this, `SapSg${i}`, id)
        )
      }
    }

    // Store connectivity config in SSM for Lambda runtime discovery
    new ssm.StringParameter(this, "SapBaseUrlParam", {
      parameterName: `/${this.stackNameBase}/connectivity/sap-base-url`,
      stringValue: this.sapBaseUrl,
    })

    // Pure-Python (only `requests`, which ships manylinux wheels), so a plain
    // local pip install suffices — no Docker/Finch fallback needed.
    const layerEntry = path.join(__dirname, "../../../lambdas/layers/sap_auth")
    this.sapAuthLayer = new lambda.LayerVersion(this, "SapAuthLayer", {
      layerVersionName: `${this.stackNameBase}-sap-auth`,
      code: lambda.Code.fromAsset(layerEntry, {
        bundling: {
          image: lambda.Runtime.PYTHON_3_13.bundlingImage,
          platform: "linux/arm64",
          command: [
            "bash", "-c",
            "pip install -r requirements.txt -t /asset-output/python -q && cp *.py /asset-output/python/",
          ],
          local: {
            tryBundle(outputDir: string): boolean {
              try {
                const { execSync } = require("child_process")
                const pythonDir = path.join(outputDir, "python")
                execSync(`mkdir -p "${pythonDir}"`, { stdio: "pipe" })
                const pipCmd = execSync("which pip3 || which pip", { stdio: "pipe" }).toString().trim()
                execSync(
                  `"${pipCmd}" install -r requirements.txt -t "${pythonDir}" --platform manylinux2014_aarch64 --python-version 3.13 --only-binary=:all: -q`,
                  { cwd: layerEntry, stdio: "pipe" },
                )
                execSync(
                  `cp ${layerEntry}/*.py "${pythonDir}"`,
                  { stdio: "pipe" },
                )
                return true
              } catch {
                return false // fall back to Docker
              }
            },
          },
        },
      }),
      compatibleRuntimes: [lambda.Runtime.PYTHON_3_13, lambda.Runtime.PYTHON_3_12],
      compatibleArchitectures: [lambda.Architecture.ARM_64, lambda.Architecture.X86_64],
      description: "Shared SAP auth: service-account credentials + error sanitization",
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    })
  }

  /** Lambda constructor props for VPC placement. Spread into SAP-facing Lambda props. */
  get lambdaVpcProps(): { vpc?: ec2.IVpc; vpcSubnets?: ec2.SubnetSelection; securityGroups?: ec2.ISecurityGroup[] } {
    if (!this.vpc) return {}
    return {
      vpc: this.vpc,
      vpcSubnets: this.vpcSubnets,
      ...(this.securityGroups ? { securityGroups: this.securityGroups } : {}),
    }
  }

  /** Set SAP env vars and attach the sap_auth layer on a SAP-facing Lambda (the poller). */
  attachToLambda(fn: lambda.Function): void {
    fn.addEnvironment("STACK_NAME_BASE", this.stackNameBase)
    fn.addEnvironment("SAP_BASE_URL_PARAM", `/${this.stackNameBase}/connectivity/sap-base-url`)
    fn.addLayers(this.sapAuthLayer)
  }
}
