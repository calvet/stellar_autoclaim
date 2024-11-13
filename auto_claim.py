import json
import time
import locale
import requests
from pathlib import Path
from datetime import datetime
import requests.packages.urllib3.exceptions
from stellar_sdk import Server, Keypair, MuxedAccount, TransactionBuilder, Network, Asset

requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)

headers_gerais = {
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/101.0.0.0 Safari/537.36',
    'accept-language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
    'accept': '*/*',
    'accept-encoding': 'gzip, deflate, br',
    'connection': 'keep-alive'
}

max_trustlines = 1
assets_not_to_sell = ['AQUA', 'XLM']


def number_format(num, places=0):
    return locale.format_string('%.*f', (places, num), True)


def check_cotacao(org_code, org_issuer, qtd, minimo, dest_code, dest_issuer=None):
    if org_code == 'XLM':
        org_type = 'native'

    elif len(org_code) <= 4:
        org_type = 'credit_alphanum4'
    else:
        org_type = 'credit_alphanum12'

    if dest_code == 'XLM':
        cotacao_url = f'https://horizon.stellar.org/paths/strict-send?destination_assets=native&source_asset_type={org_type}&source_asset_code={org_code}&source_asset_issuer={org_issuer}&source_amount={qtd}'
    else:
        cotacao_url = f'https://horizon.stellar.org/paths/strict-send?destination_assets={dest_code}%3A{dest_issuer}&source_asset_type={org_type}&source_asset_issuer={org_issuer}&source_asset_code={org_code}&source_amount={qtd}'

    get_cotacao = requests.get(
        url=cotacao_url,
        headers=headers_gerais,
        timeout=60,
        verify=False
    )

    cotacao = get_cotacao.json()

    if len(cotacao) < 1:
        return 0
    elif '_embedded' not in cotacao:
        return 0
    elif 'records' not in cotacao['_embedded']:
        return 0
    elif len(cotacao['_embedded']['records']) < 1:
        return 0
    else:
        valor_mercado = cotacao['_embedded']['records'][0]['destination_amount']

        if float(valor_mercado) > minimo:
            valor_mercado = number_format(float(valor_mercado), 7)

            return valor_mercado
        else:
            valor_mercado = number_format(float(valor_mercado), 7)

            return valor_mercado


def proceed_trans(account, trusts, claims, valores_claims, myprivatekey):
    server = Server('https://horizon.stellar.org')

    print('GENERATING XDR...')

    base_fee = 120

    muxed = MuxedAccount(account_id=account, account_muxed_id=1)

    # print(muxed.account_muxed)

    muxed = MuxedAccount.from_account(muxed.account_muxed)

    account = server.load_account(account)

    print(f'ACCOUNT ID: {muxed.account_id}\nMUXED ACCOUNT ID: {muxed.account_muxed_id}')

    native_asset = Asset('XLM')

    path = {}
    assets = {}

    for key, clx in valores_claims.items():
        if clx['dest_code'] == 'XLM' or clx['dest_code'] == '' or 'dest_code' not in clx:
            asset_to_sell = Asset(clx['org_code'], clx['org_issuer'])
            path_payments = Server.strict_send_paths(server, source_asset=asset_to_sell, source_amount=clx['org_valor'],
                                                     destination=[native_asset]).call()
            path[key] = [Asset('XLM') for _ in path_payments['_embedded']['records']]
        else:
            asset_to_sell = Asset(clx['org_code'], clx['org_issuer'])
            path_payments = Server.strict_send_paths(server, source_asset=asset_to_sell, source_amount=clx['org_valor'],
                                                     destination=[native_asset]).call()
            path[key] = [asset_to_sell for _ in path_payments['_embedded']['records']]

    transaction = TransactionBuilder(
        source_account=account,
        network_passphrase=Network.PUBLIC_NETWORK_PASSPHRASE,
        base_fee=base_fee
    )

    transaction.add_time_bounds(int(time.time()) - 60, int(time.time()) + 300)

    for key, tline in trusts.items():
        asset = tline.split(':')

        assets[asset[0]] = Asset(asset[0], asset[1])

        transaction.append_change_trust_op(asset=assets[asset[0]])

    for claim in claims:
        transaction.append_claim_claimable_balance_op(balance_id=claim, source=muxed)

    for key, clx in valores_claims.items():
        if clx['dest_code'] == 'XLM':
            clx['dest_code'] = 'XLM'
            clx['dest_issuer'] = None
            clx['dest_min'] = '0.0001'
        else:
            clx['dest_issuer'] = clx['dest_issuer']

        assets[clx['org_code']] = Asset(clx['org_code'], clx['org_issuer'])
        assets[clx['dest_code']] = Asset(clx['dest_code'], clx['dest_issuer'])

        # TODO: validar se asset nao esta na lista para ser ignorada
        if clx['org_code'] not in assets_not_to_sell:
            transaction.append_path_payment_strict_send_op(
                destination=muxed,  # account,
                send_asset=assets[clx['org_code']],
                send_amount=clx['org_valor'],
                dest_asset=assets[clx['dest_code']],
                dest_min=clx['dest_min'],
                path=path[key]
            )

            transaction.append_change_trust_op(
                asset=assets[clx['org_code']],
                limit='0'
            )
        else:
            print(f'ASSET {clx["org_code"]} (worth {clx["org_valor"]} XLM) NOT SOLD!')

    tx = transaction.build()

    print('')

    try:
        if myprivatekey[0:1] == 'S' and len(myprivatekey) == 56:
            stellar_keypair = Keypair.from_secret(myprivatekey)
            account_priv_key = stellar_keypair.secret
            tx.sign(account_priv_key)

            try:
                response = server.submit_transaction(tx)

                print('TRANSACTION WAS SUBMITED SUCCESSFULLY!', response['successful'], response['id'])
            except Exception as e:
                print('TRANSACTION FAILED!')

                print(e)

                if e['title'] == 'Timeout':
                    print('Error: transaction timeout. Try again!')

                if 'extras' in e:
                    dct = e.extras

                    if dct['extras']['result_code']['transaction'] == 'tx_failed':
                        for e_code in dct['extras']['result_code']['transaction']['operations']:
                            if e_code == 'op_low_reserve':
                                print('Error: not enough funds to create a new Offer')
                            elif e_code == 'op_no_trust':
                                print('Error: destination missing a trust line for asset')
                            elif e_code == 'op_src_no_trust':
                                print('Error: no trust line on source account')
                            elif e_code == 'op_invalid_limit':
                                print('Error: cannot drop limit below balance, cannot create with a limit of 0')
                            else:
                                print(e_code)
                    else:
                        print(e.extras['result_codes'])
        else:
            print(tx.to_xdr())
    except Exception as e:
        print(e)


def verificar_conta(ppublic_address, pprivate_address):
    trustlines = {}
    ids_claims = []
    valor_claims = {}

    if ppublic_address[0:1] != 'G' or len(ppublic_address) != 56:
        print('ERROR! YOUR PUBLIC ADDRESS IS NOT VALID!')

        exit()

    if pprivate_address[0:1] != 'S' or len(pprivate_address) != 56:
        print('ERROR! YOUR PRIVATE ADDRESS IS NOT VALID')

        exit()

    wlt = '[' + ppublic_address[-10:] + ']'

    arrecadacao = 0

    print(wlt)

    print('-' * 90)

    print('IGNORING SELL OPERATION FOR THE FOLLOWING ASSETS: {}'.format(', '.join(assets_not_to_sell)))

    print('-' * 90)

    get_claimable = requests.get(
        url=f'https://horizon.stellar.org/claimable_balances/?limit=200&claimant={ppublic_address}',
        headers=headers_gerais,
        timeout=60,
        verify=False
    )

    claimable_data = get_claimable.json()

    claimable_records = claimable_data['_embedded']['records']

    if len(claimable_records) < 1:
        print(f'NO CLAIMABLE BALANCES FOUND!\n')

    get_account = requests.get(
        url=f'https://horizon.stellar.org/accounts/{ppublic_address}',
        headers=headers_gerais,
        timeout=60,
        verify=False
    )

    account_data = get_account.json()

    if 'balances' not in account_data:
        print(f'NO BALANCES FOUND! (ACCOUNT MAY NOT EXIST?)\n')

        return

    account_balances = account_data['balances']

    for ac_balance in account_balances:
        if 'asset_code' in ac_balance:
            asset = ac_balance['asset_code']
        else:
            asset = 'XLM'

        print(f'BALANCE {asset}: {ac_balance["balance"]}')

    print('')

    if len(claimable_records) > 0:
        for claimable in claimable_records:
            asset = claimable['asset'].split(':')

            print('(' + asset[0] + ') ->', end=' ')

            possui_trustline = False

            for balance in account_balances:
                if 'asset_code' in balance and balance['asset_code'] == asset[0] and 'asset_issuer' in balance and \
                        balance['asset_issuer'] == asset[1]:
                    possui_trustline = True

                    break

            pode_claim = False
            claimants = claimable['claimants']

            for claimant in claimants:
                if claimant['destination'] == public_address:
                    if 'unconditional' in claimant['predicate'] and claimant['predicate']['unconditional']:
                        print('(UNCONDITIONAL)', end=' ')

                        pode_claim = True
                    elif 'abs_before' in claimant['predicate']:
                        ate_quando = datetime.fromisoformat(claimant['predicate']['abs_before'].replace('Z', ''))

                        if ate_quando < datetime.now():
                            print('(EXPIRED)', end=' ')

                            pode_claim = False
                        else:
                            print('(VALID)', end=' ')

                            pode_claim = True

                    if pode_claim:
                        get_asset = requests.get(
                            url=f'https://horizon.stellar.org/assets?asset_code={asset[0]}&asset_issuer={asset[1]}',
                            headers=headers_gerais,
                            timeout=60,
                            verify=False
                        )

                        asset_data = get_asset.json()

                        asset_records = asset_data['_embedded']['records'][0]

                        if not asset_records['flags']['auth_required']:
                            pode_claim = True
                        else:
                            print('(NEEDS AUTHORIZATION)', end=' ')

                            pode_claim = False
            if not pode_claim:
                print('(CANNOT CLAIN [YET?])', end=' ')

            if not possui_trustline and pode_claim:
                if len(trustlines) < max_trustlines:
                    valor_mercado = check_cotacao(asset[0], asset[1], claimable['amount'], 0.0001, 'XLM', None)

                    if float(valor_mercado) > 0.0001:
                        print(f'(VALID) {valor_mercado} XLM', end=' ')

                        arrecadacao += float(valor_mercado)

                        id_asset = claimable['asset'].replace(':', '_')

                        trustlines[id_asset] = claimable['asset']

                        claim_id = claimable['id']

                        ids_claims.append(claim_id)

                        valor_claims[claim_id] = {
                            'org_valor': claimable['amount'],
                            'org_code': asset[0],
                            'org_issuer': asset[1],
                            'dest_code': 'XLM',
                            'valor_mercado': valor_mercado
                        }
                    else:
                        print(f'(INVALID) {valor_mercado} XLM', end=' ')
                else:
                    print('')

                    print('WILL NOT CONTINUE. MAX TRUSTLINES!')

                    break

            print('')

    print('')

    if len(ids_claims) > 0:
        value_arracadacao = number_format(arrecadacao, 7)

        print(f'{wlt} COLLECTING: {value_arracadacao} XLM..')

        try:
            proceed_trans(ppublic_address, trustlines, ids_claims, valor_claims, pprivate_address)
        except:
            print(f'{wlt} FAILED TO COLLECT: {value_arracadacao} XLM!')
    else:
        print(f'{wlt} NOTHING TO COLLECT!')


if __name__ == '__main__':
    contas_data = json.load(open(str(Path(__file__).parent.absolute()) + '/accounts_data.json'))

    while True:
        for public_address, private_address in contas_data.items():
            if public_address == '_comment':
                continue

            print('-' * 90)

            verificar_conta(public_address, private_address)
