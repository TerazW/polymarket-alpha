#!/usr/bin/env python
"""
钱包设置工具
用于生成新的 Polygon 钱包（仅用于 API 认证）
"""

from eth_account import Account
import secrets

def generate_new_wallet():
    """
    生成新的以太坊/Polygon 钱包
    
    注意：
    - 此钱包不需要任何资金
    - 仅用于 Polymarket CLOB API 认证
    - 私钥将显示一次，请妥善保存
    """
    print("\n" + "="*70)
    print("🔐 Polymarket CLOB API - Wallet Generator")
    print("="*70)
    
    print("\n📝 Generating new Polygon wallet...")
    print("   (This wallet is for API authentication only, no funds needed)")
    
    # 生成随机私钥
    private_key = "0x" + secrets.token_hex(32)
    
    # 创建账户
    account = Account.from_key(private_key)
    
    print("\n" + "="*70)
    print("✅ Wallet Generated Successfully!")
    print("="*70)
    
    print(f"\n📍 Wallet Address:")
    print(f"   {account.address}")
    
    print(f"\n🔑 Private Key:")
    print(f"   {private_key}")
    
    print("\n" + "="*70)
    print("⚠️  IMPORTANT INSTRUCTIONS:")
    print("="*70)
    
    print("""
1. Copy the Private Key above

2. Open your .env file (or create it from .env.example)

3. Set the PRIVATE_KEY:
   PRIVATE_KEY={key}

4. Save the .env file

5. You're ready to use CLOB API!
""".format(key=private_key))
    
    print("="*70)
    print("🔒 Security Notes:")
    print("="*70)
    
    print("""
✓ This wallet is ONLY for API authentication
✓ No funds are required
✓ Keep the private key secure
✓ Don't share it publicly
✓ Don't commit .env to Git (already in .gitignore)

If you lose this key:
→ Simply run this script again to generate a new one
→ You'll need to re-initialize API credentials (automatic)
""")
    
    print("\n" + "="*70)
    
    return private_key, account.address


def verify_existing_wallet(private_key: str):
    """
    验证现有私钥
    
    Args:
        private_key: 私钥字符串
    """
    print("\n" + "="*70)
    print("🔍 Verifying Existing Wallet")
    print("="*70)
    
    try:
        # 确保私钥格式正确
        if not private_key.startswith('0x'):
            private_key = '0x' + private_key
        
        # 创建账户
        account = Account.from_key(private_key)
        
        print(f"\n✅ Valid wallet!")
        print(f"\n📍 Address: {account.address}")
        print(f"🔑 Private Key: {private_key[:10]}...{private_key[-6:]}")
        
        print("\n✅ You can use this wallet for CLOB API authentication")
        
        return True
        
    except Exception as e:
        print(f"\n❌ Invalid private key: {e}")
        print("\n💡 To generate a new wallet, choose option 1")
        
        return False


def main():
    """主函数"""
    print("\n" + "="*70)
    print("🚀 Market Sensemaking - Wallet Setup Tool")
    print("="*70)
    
    print("""
This tool helps you set up a Polygon wallet for Polymarket CLOB API.

What you need to know:
• This wallet is ONLY for API authentication
• No funds are required
• The private key will be stored in your .env file
• Never share your private key publicly

Choose an option:
1. Generate a new wallet (recommended for new users)
2. Verify an existing wallet
3. Exit
""")
    
    choice = input("Enter your choice (1/2/3): ").strip()
    
    if choice == "1":
        private_key, address = generate_new_wallet()
        
        # 询问是否自动写入 .env
        auto_write = input("\n🤔 Automatically write to .env file? (y/n): ").strip().lower()
        
        if auto_write == 'y':
            try:
                import os
                from pathlib import Path
                
                # 检查 .env 是否存在
                env_file = Path('.env')
                
                if env_file.exists():
                    print("\n⚠️  .env file already exists")
                    overwrite = input("   Overwrite PRIVATE_KEY? (y/n): ").strip().lower()
                    
                    if overwrite != 'y':
                        print("\n✅ Cancelled. Please update .env manually.")
                        return
                    
                    # 读取现有内容
                    with open('.env', 'r') as f:
                        lines = f.readlines()
                    
                    # 更新 PRIVATE_KEY
                    updated = False
                    for i, line in enumerate(lines):
                        if line.startswith('PRIVATE_KEY='):
                            lines[i] = f'PRIVATE_KEY={private_key}\n'
                            updated = True
                            break
                    
                    # 如果没找到 PRIVATE_KEY 行，添加
                    if not updated:
                        lines.append(f'\nPRIVATE_KEY={private_key}\n')
                    
                    # 写回文件
                    with open('.env', 'w') as f:
                        f.writelines(lines)
                    
                    print("\n✅ Updated .env file successfully!")
                    
                else:
                    # 从模板创建
                    if Path('.env.example').exists():
                        with open('.env.example', 'r') as f:
                            content = f.read()
                        
                        # 替换 PRIVATE_KEY
                        content = content.replace(
                            'PRIVATE_KEY=0x0000000000000000000000000000000000000000000000000000000000000000',
                            f'PRIVATE_KEY={private_key}'
                        )
                        
                        with open('.env', 'w') as f:
                            f.write(content)
                        
                        print("\n✅ Created .env file from template!")
                    else:
                        # 创建简单的 .env
                        with open('.env', 'w') as f:
                            f.write(f'PRIVATE_KEY={private_key}\n')
                        
                        print("\n✅ Created new .env file!")
                
                print(f"\n🎉 All set! You can now use the CLOB API.")
                print(f"   Run: python polymarket_clob_api.py (to test)")
                
            except Exception as e:
                print(f"\n❌ Error writing to .env: {e}")
                print(f"   Please copy the private key manually")
    
    elif choice == "2":
        private_key = input("\nEnter your private key (with or without 0x): ").strip()
        verify_existing_wallet(private_key)
    
    elif choice == "3":
        print("\n👋 Goodbye!")
    
    else:
        print("\n❌ Invalid choice. Please run the script again.")
    
    print("\n" + "="*70)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 Cancelled by user. Goodbye!")
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
