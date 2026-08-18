// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import * as cdk from "aws-cdk-lib"
import { Template } from "aws-cdk-lib/assertions"
import { ObservabilityConstruct } from "../lib/constructs/observability"

// Regression guard from a real failed deployment. The trail used to be created
// unconditionally, and CloudTrail allows only 5 trails per Region as a hard
// limit — so deploying a third copy of this sample into an account that already
// had baseline trails failed the whole backend stack with:
//
//   "User: <account> already has 5 trails in us-east-1."
//
// It is now opt-in. These tests pin both states, because a regression in either
// direction is expensive: on by default breaks deploys, and a broken flag
// silently drops the M7 autonomy-change alarm.

function synth(auditTrailEnabled?: boolean): Template {
  const app = new cdk.App()
  const stack = new cdk.Stack(app, "TestStack", {
    env: { account: "111122223333", region: "us-east-1" },
  })
  new ObservabilityConstruct(stack, "Observability", {
    stackNameBase: "test-proj",
    metricsNamespace: "ERPAgent",
    auditTrailEnabled,
  })
  return Template.fromStack(stack)
}

describe("ObservabilityConstruct audit trail is opt-in", () => {
  test("creates no trail, bucket, or log group by default", () => {
    const template = synth()
    template.resourceCountIs("AWS::CloudTrail::Trail", 0)
    template.resourceCountIs("AWS::Logs::MetricFilter", 0)
    // The trail's dedicated bucket and log group must go with it.
    template.resourceCountIs("AWS::S3::Bucket", 0)
    template.resourceCountIs("AWS::Logs::LogGroup", 0)
  })

  test("creates no trail when explicitly disabled", () => {
    synth(false).resourceCountIs("AWS::CloudTrail::Trail", 0)
  })

  test("creates the trail and the autonomy alarm when enabled", () => {
    const template = synth(true)
    template.resourceCountIs("AWS::CloudTrail::Trail", 1)
    template.hasResourceProperties("AWS::CloudTrail::Trail", {
      TrailName: "test-proj-ssm-trail",
    })
    template.hasResourceProperties("AWS::CloudWatch::Alarm", {
      AlarmName: "test-proj-autonomy-change",
    })
    template.resourceCountIs("AWS::Logs::MetricFilter", 1)
  })

  test("the always-on alarms survive with the trail disabled", () => {
    const template = synth(false)
    for (const alarmName of [
      "test-proj-dlq-messages",
      "test-proj-agent-failure-rate",
      "test-proj-agent-cost-high",
    ]) {
      template.hasResourceProperties("AWS::CloudWatch::Alarm", { AlarmName: alarmName })
    }
  })

  test("the dashboard renders without the optional alarm", () => {
    // A stale `undefined` in the AlarmStatusWidget alarm list would throw here.
    synth(false).resourceCountIs("AWS::CloudWatch::Dashboard", 1)
  })
})
