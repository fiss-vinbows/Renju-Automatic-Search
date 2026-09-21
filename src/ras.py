"""
RAS（Renju Automatic Search）exe 用エントリポイント（GUI 版）。

RAS.exe は Rapfi（YixinBoard）フォルダ直下のサブフォルダ RAS に置く。debuglog.txt は親フォルダから読む。
  ・探索時間などの設定は GUI で編集し、同じフォルダの monitor_config.json に保存される。
  ・「自動探索モード」のトグルをオンにすると監視と自動送信が始まる。
  ・入力欄の校正値は sender_config.json に保存される（GUI の「入力欄を校正」）。
  ・RAS.exe --console を付けると、GUI を使わず旧来のコンソール版（monitor.py --auto）で動く。
"""

import sys


def main():
    if "--console" in sys.argv:
        sys.argv.remove("--console")
        import monitor
        if "--auto" not in sys.argv:
            sys.argv.append("--auto")
        try:
            monitor.main()
        finally:
            try:
                input("\n何かキーを押すと閉じます...")
            except Exception:
                pass
        return
    import gui
    gui.main()


if __name__ == "__main__":
    main()
