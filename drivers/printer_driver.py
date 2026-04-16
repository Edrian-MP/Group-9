import os
import datetime
import threading
import config

class InvoicePrinter:
    def __init__(self):
        self.printer_name = getattr(config, 'PRINTER_NAME', 'POS-58')
        self.width = 32

    def generate_receipt_text(
        self,
        cart,
        grand_total,
        tendered=None,
        payment_method="Cash",
        transaction_id="",
        seller_name=""
    ):
        now = datetime.datetime.now()
        date_str = now.strftime("%Y-%m-%d %H:%M:%S")
        receipt = "\n\n"
        def center(text):
            padding = max(0, (self.width - len(text)) // 2)
            return (" " * padding) + text + "\n"
        receipt += "-" * self.width + "\n"
        receipt += center("FRESH PRODUCE POS")
        receipt += center("Balayan, Batangas")
        receipt += "-" * self.width + "\n"
        receipt += f"Date: {date_str}\n"
        if transaction_id:
            receipt += f"Ref No: {transaction_id}\n"
        seller_name = str(seller_name or "").strip()
        if seller_name:
            receipt += f"Seller: {seller_name}\n"
        receipt += "-" * self.width + "\n"
        receipt += f"{'Item':<14} {'Kg':<6} {'Total':>6}\n"
        receipt += "-" * self.width + "\n"
        for item in cart:
            name = item['name'][:14] 
            qty = f"{item['weight']:.2f}"
            price = f"{item['total']:.2f}"
            receipt += f"{name:<14} {qty:<6} {price:>6}\n"
        receipt += "-" * self.width + "\n"
        total_line = f"PHP {grand_total:.2f}"
        receipt += f"{'GRAND TOTAL:':<16}{total_line:>12}\n"
        receipt += f"{'METHOD:':<16}{payment_method:>12}\n"
        if payment_method == "Cash" and tendered is not None:
            change = tendered - grand_total
            receipt += f"{'CASH:':<16}{f'PHP {tendered:.2f}':>12}\n"
            receipt += f"{'CHANGE:':<16}{f'PHP {change:.2f}':>12}\n"
        receipt += "-" * self.width + "\n"
        receipt += center("Maraming Salamat Po!")
        receipt += "\n\n\n\n" 
        return receipt

    def _run_print_cmd(self, text_content):
        usb_port = '/dev/usb/lp0'
        try:
            init_cmd = b'\x1b\x40'
            codepage_cmd = b'\x1b\x74\x00'
            content_bytes = text_content.encode('ascii', errors='replace')
            cut_cmd = b'\x1d\x56\x01'
            full_payload = init_cmd + codepage_cmd + content_bytes + cut_cmd
            fd = os.open(usb_port, os.O_WRONLY | os.O_SYNC)
            try:
                os.write(fd, full_payload)
                print(f"[Printer] Successfully wrote {len(full_payload)} bytes to {usb_port}")
            finally:
                os.close(fd)
        except Exception as e:
            print(f"[Printer] Hardware Error: {e}")

    def print_receipt(
        self,
        cart,
        grand_total,
        tendered=None,
        payment_method="Cash",
        transaction_id="",
        seller_name=""
    ):
        text_content = self.generate_receipt_text(
            cart,
            grand_total,
            tendered,
            payment_method,
            transaction_id,
            seller_name
        )
        t = threading.Thread(target=self._run_print_cmd, args=(text_content,), daemon=True)
        t.start()
        return True

