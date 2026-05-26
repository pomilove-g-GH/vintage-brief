#!/usr/bin/env python3
"""
업데이트 버튼 비밀번호 설정 스크립트
실행: python set-password.py
"""
import hashlib
import getpass
import re
import os

def main():
    print("=== Vintage Daily Digest — 업데이트 비밀번호 설정 ===\n")

    pw = getpass.getpass("비밀번호 입력: ")
    if not pw:
        print("비밀번호를 입력해 주세요.")
        return

    pw2 = getpass.getpass("비밀번호 확인: ")
    if pw != pw2:
        print("비밀번호가 일치하지 않습니다.")
        return

    h = hashlib.sha256(pw.encode("utf-8")).hexdigest()
    print(f"\nSHA-256: {h}")

    manifest_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "manifest.js")
    with open(manifest_path, "r", encoding="utf-8") as f:
        content = f.read()

    new_content = re.sub(
        r'updatePasswordHash:\s*"[^"]*"',
        f'updatePasswordHash: "{h}"',
        content
    )

    if new_content == content:
        print("\n⚠️  manifest.js 에서 updatePasswordHash 필드를 찾지 못했습니다.")
        return

    with open(manifest_path, "w", encoding="utf-8") as f:
        f.write(new_content)

    print("✅ manifest.js 업데이트 완료! 비밀번호가 저장되었습니다.")
    print("   (비밀번호 원문은 저장되지 않으며, SHA-256 해시만 보관됩니다.)")

if __name__ == "__main__":
    main()
