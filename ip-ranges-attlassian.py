#!/usr/bin/env python3
"""
Fetches Atlassian IP ranges from https://ip-ranges.atlassian.com/
Interactively selects VPC → Security Group → Products,
then updates AWS Security Groups with SSH (TCP/22) ingress rules.
"""

import json
import sys
import getpass
import math
import urllib.request
import urllib.error
from datetime import datetime

try:
    import boto3
    from botocore.exceptions import ClientError, NoCredentialsError
except ImportError:
    print("[-] boto3 is required. Install it with: pip install boto3")
    sys.exit(1)

SSH_PORT = 22
ATLASSIAN_URL = "https://ip-ranges.atlassian.com/"

# ─── AWS Credentials ───────────────────────────────────────────────────────────

def prompt_aws_credentials():
    print("\n" + "═" * 60)
    print("  AWS Credentials")
    print("═" * 60)
    aws_access_key = input("  AWS Access Key ID     : ").strip()
    aws_secret_key = getpass.getpass("  AWS Secret Access Key : ")
    aws_region     = input("  AWS Region [eu-south-2]: ").strip() or "eu-south-2"
    print("═" * 60 + "\n")
    session = boto3.Session(
        aws_access_key_id=aws_access_key,
        aws_secret_access_key=aws_secret_key,
        region_name=aws_region,
    )
    return session

# ─── VPC Selection ─────────────────────────────────────────────────────────────

def list_vpcs(ec2) -> list:
    resp = ec2.describe_vpcs()
    vpcs = []
    for v in resp["Vpcs"]:
        name = ""
        for tag in v.get("Tags", []):
            if tag["Key"] == "Name":
                name = tag["Value"]
                break
        vpcs.append({
            "id":      v["VpcId"],
            "cidr":    v["CidrBlock"],
            "name":    name,
            "default": v.get("IsDefault", False),
        })
    return sorted(vpcs, key=lambda x: x["id"])


def select_vpc_interactive(vpcs: list) -> dict:
    num_w  = len(str(len(vpcs))) + 2   # e.g. "[4]" = 3 chars
    id_w   = 24
    cidr_w = 18
    sep    = "  " + "─" * 68

    print("\n[*] Available VPCs:\n")
    print(f"  {'#':<{num_w}}  {'VPC ID':<{id_w}}  {'CIDR':<{cidr_w}}  Name")
    print(sep)

    for i, v in enumerate(vpcs, start=1):
        tag  = " (default)" if v["default"] else ""
        name = (v["name"] + tag) if v["name"] else tag.strip()
        idx_str = f"[{i}]"
        print(f"  {idx_str:<{num_w}}  {v['id']:<{id_w}}  {v['cidr']:<{cidr_w}}  {name}")

    print()
    while True:
        raw = input("  Select VPC number: ").strip()
        try:
            choice = int(raw)
            if 1 <= choice <= len(vpcs):
                return vpcs[choice - 1]
        except ValueError:
            pass
        print(f"  [-] Enter a number between 1 and {len(vpcs)}.")

# ─── Security Group Selection ──────────────────────────────────────────────────

def list_sgs_for_vpc(ec2, vpc_id: str) -> list:
    resp = ec2.describe_security_groups(
        Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
    )
    sgs = []
    for sg in resp["SecurityGroups"]:
        sgs.append({
            "id":   sg["GroupId"],
            "name": sg["GroupName"],
            "desc": sg.get("Description", ""),
        })
    return sorted(sgs, key=lambda x: x["id"])


def select_sg_interactive(sgs: list, vpc_id: str) -> dict:
    num_w = len(str(len(sgs))) + 2   # e.g. "[26]" = 4 chars
    id_w  = 24
    sep   = "  " + "─" * 80

    print(f"\n[*] Security Groups in VPC {vpc_id}:\n")
    print(f"  {'#':<{num_w}}  {'SG ID':<{id_w}}  {'Name / Description'}")
    print(sep)

    for i, sg in enumerate(sgs, start=1):
        # Use name if it's meaningful, else fall back to description
        label = sg["name"] if sg["name"] and sg["name"] != "default" else sg["desc"]
        # Append description in parens when name and desc differ and are both set
        if sg["name"] and sg["desc"] and sg["name"] != sg["desc"]:
            label = f"{sg['name']}  —  {sg['desc']}"
        idx_str = f"[{i}]"
        print(f"  {idx_str:<{num_w}}  {sg['id']:<{id_w}}  {label}")

    print()
    while True:
        raw = input("  Select Security Group number: ").strip()
        try:
            choice = int(raw)
            if 1 <= choice <= len(sgs):
                return sgs[choice - 1]
        except ValueError:
            pass
        print(f"  [-] Enter a number between 1 and {len(sgs)}.")

# ─── Atlassian helpers ─────────────────────────────────────────────────────────

def fetch_ip_ranges(url: str) -> dict:
    print(f"\n[*] Fetching IP ranges from {url} ...")
    with urllib.request.urlopen(url, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def is_ipv4(cidr: str) -> bool:
    return ":" not in cidr


def get_available_products(data: dict) -> list:
    products = set()
    for item in data.get("items", []):
        raw = item.get("product", [])
        if isinstance(raw, str):
            raw = [raw]
        for p in raw:
            products.add(p.strip())
    return sorted(products)


def select_products_interactive(products: list) -> list:
    print("\n[*] Available products:")
    print(f"    {'0':<4} ALL (all products)")
    for i, p in enumerate(products, start=1):
        print(f"    {str(i):<4} {p}")

    print("\n[?] Enter the numbers of the products to include.")
    print("    Separate with commas or spaces  (e.g.: 1,3,5 or 1 3 5)")
    print("    Enter 0 for all products.\n")

    while True:
        raw = input(">>> ").strip()
        if not raw:
            continue
        tokens = raw.replace(",", " ").split()
        try:
            choices = [int(t) for t in tokens]
        except ValueError:
            print("[-] Numbers only, please.")
            continue
        if any(c < 0 or c > len(products) for c in choices):
            print(f"[-] Numbers must be between 0 and {len(products)}.")
            continue
        if 0 in choices:
            return products
        seen, selected = set(), []
        for c in choices:
            p = products[c - 1]
            if p not in seen:
                seen.add(p)
                selected.append(p)
        return selected


def extract_cidrs_for_products(data: dict, selected_products: list) -> list:
    selected_set = set(selected_products)
    cidrs = set()
    skipped_v6 = 0
    for item in data.get("items", []):
        raw = item.get("product", [])
        if isinstance(raw, str):
            raw = [raw]
        if not {p.strip() for p in raw}.intersection(selected_set):
            continue
        cidr = item.get("cidr")
        if not cidr:
            continue
        if is_ipv4(cidr):
            cidrs.add(cidr)
        else:
            skipped_v6 += 1
    if skipped_v6:
        print(f"[*] Skipped {skipped_v6} IPv6 CIDRs")
    return sorted(cidrs)

# ─── AWS SG helpers ────────────────────────────────────────────────────────────

def get_existing_ssh_cidrs(ec2, sg_id: str) -> set:
    try:
        resp = ec2.describe_security_groups(GroupIds=[sg_id])
    except ClientError as e:
        print(f"  [-] Cannot describe {sg_id}: {e}")
        return set()
    sg = resp["SecurityGroups"][0]
    cidrs = set()
    for rule in sg.get("IpPermissions", []):
        proto = rule.get("IpProtocol")
        from_p = rule.get("FromPort", -1)
        to_p   = rule.get("ToPort", -1)
        if proto == "-1" or (proto == "tcp" and from_p <= SSH_PORT <= to_p):
            for ip_range in rule.get("IpRanges", []):
                cidrs.add(ip_range["CidrIp"])
    return cidrs


def add_ssh_ingress_rules(ec2, sg_id: str, cidrs_to_add: list) -> bool:
    ip_ranges = [
        {
            "CidrIp": cidr,
            "Description": f"Atlassian IP (added {datetime.utcnow().strftime('%Y-%m-%d')})",
        }
        for cidr in cidrs_to_add
    ]
    try:
        ec2.authorize_security_group_ingress(
            GroupId=sg_id,
            IpPermissions=[{
                "IpProtocol": "tcp",
                "FromPort": SSH_PORT,
                "ToPort": SSH_PORT,
                "IpRanges": ip_ranges,
            }],
        )
        return True
    except ClientError as e:
        print(f"  [-] Error adding rules to {sg_id}: {e}")
        return False

# ─── Display helpers ───────────────────────────────────────────────────────────

def print_analysis(sg_id: str, vpc_id: str, existing: set, missing: list, unknown: set):
    W = 65
    print(f"\n{'═'*W}")
    print(f"  ANALYSIS — Security Groups")
    print(f"{'═'*W}")
    print(f"  SG  : {sg_id}  (VPC: {vpc_id})")
    print(f"  SSH CIDRs already present : {len(existing)}")
    print(f"  CIDRs to ADD              : {len(missing)}")
    print(f"  CIDRs not in Atlassian    : {len(unknown)}  (UNKNOWN)")

    if missing:
        print(f"\n  Missing CIDRs (will be added):")
        for c in sorted(missing):
            print(f"    + {c}")

    if unknown:
        print(f"\n  Unknown CIDRs (already in SG but NOT in Atlassian list):")
        for c in sorted(unknown):
            print(f"    ? {c}")


def print_final_summary(sg_id: str, vpc_id: str, orig: set, added: set, atlassian_set: set):
    W = 65
    all_cidrs = orig | added
    print(f"\n{'═'*W}")
    print(f"  Security Group : {sg_id}")
    print(f"  VPC            : {vpc_id}")
    print(f"{'─'*W}")
    print(f"  {'CIDR':<26}  STATUS")
    print(f"{'─'*W}")

    for cidr in sorted(all_cidrs):
        if cidr in added:
            tag = "NEW"
        elif cidr in orig and cidr not in atlassian_set:
            tag = "UNKNOWN"
        else:
            tag = "ORIG"
        print(f"  {cidr:<26}  {tag}")

    orig_count    = len(orig - added)
    unknown_count = len(orig - atlassian_set)
    print(f"{'─'*W}")
    print(f"  ORIG: {orig_count}  |  NEW: {len(added)}  |  UNKNOWN: {unknown_count}")
    print(f"{'═'*W}")

# ─── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("╔══════════════════════════════════════════════════════════╗")
    print("║   Atlassian IP Ranges → AWS Security Group Updater       ║")
    print("╚══════════════════════════════════════════════════════════╝")

    # 1. AWS credentials
    session = prompt_aws_credentials()
    ec2 = session.client("ec2")
    try:
        ec2.describe_account_attributes()
        print("[+] AWS credentials validated OK")
    except (ClientError, NoCredentialsError) as e:
        print(f"[-] AWS authentication failed: {e}")
        sys.exit(1)

    # 2. VPC selection
    print("\n[*] Loading VPCs...")
    vpcs = list_vpcs(ec2)
    if not vpcs:
        print("[-] No VPCs found.")
        sys.exit(1)
    selected_vpc = select_vpc_interactive(vpcs)
    print(f"\n[+] Selected VPC: {selected_vpc['id']}  ({selected_vpc['cidr']})")

    # 3. Security Group selection
    print("\n[*] Loading Security Groups...")
    sgs = list_sgs_for_vpc(ec2, selected_vpc["id"])
    if not sgs:
        print(f"[-] No Security Groups found in VPC {selected_vpc['id']}.")
        sys.exit(1)
    selected_sg = select_sg_interactive(sgs, selected_vpc["id"])
    print(f"\n[+] Selected SG : {selected_sg['id']}  — {selected_sg['desc']}")

    # 4. Fetch Atlassian ranges
    try:
        data = fetch_ip_ranges(ATLASSIAN_URL)
    except urllib.error.URLError as e:
        print(f"[-] Failed to fetch Atlassian ranges: {e}")
        sys.exit(1)

    # 5. Product selection
    products = get_available_products(data)
    selected_products = select_products_interactive(products)

    atlassian_cidrs = extract_cidrs_for_products(data, selected_products)

    print(f"[*] Selected products: {', '.join(selected_products)}")
    print(f"[*] Total Atlassian IPv4 CIDRs: {len(atlassian_cidrs)}")

    if not atlassian_cidrs:
        print("[-] No IPv4 CIDRs found for the selected products. Exiting.")
        sys.exit(0)

    atlassian_set = set(atlassian_cidrs)

    # 6. Analyse the selected Security Group
    sg_id  = selected_sg["id"]
    vpc_id = selected_vpc["id"]

    existing = get_existing_ssh_cidrs(ec2, sg_id)
    missing  = sorted(atlassian_set - existing)
    unknown  = existing - atlassian_set

    print_analysis(sg_id, vpc_id, existing, missing, unknown)

    # 7. Confirm changes
    if not missing:
        print("\n[+] Security Group is already up to date. Nothing to add.")
    else:
        print(f"\n{'═'*65}")
        confirm = input("  Apply changes? [yes/NO]: ").strip().lower()
        if confirm not in ("yes", "y"):
            print("[*] Aborted. No changes were made.")
            sys.exit(0)

        print(f"\n[*] Adding {len(missing)} rule(s) to {sg_id} ...")
        ok = add_ssh_ingress_rules(ec2, sg_id, missing)
        if ok:
            print(f"[✓] Rules added successfully.")
        else:
            print(f"[-] Some rules could not be added.")

    # 8. Final summary
    added = set(missing) if missing else set()
    print("\n\n  FINAL SUMMARY")
    print_final_summary(sg_id, vpc_id, existing, added, atlassian_set)


if __name__ == "__main__":
    main()
