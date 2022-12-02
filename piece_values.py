import argparse
import fileinput
from math import log
import re

import pandas
from sklearn.linear_model import LogisticRegression
from tqdm import tqdm

from common import sum_line_count, parse_epd


SCORE = {'1-0': 1, '0-1': 0, '1/2-1/2': 0.5}


def has_imbalance(pieces, imbalance):
    return all(pieces.count(p) - pieces.count(p.swapcase()) >= imbalance.count(p) - imbalance.count(p.swapcase()) for p in set(imbalance))


def game_phase(phases, max_pieces, num_board_pieces):
    return phases - 1 - min(max(int(phases * (num_board_pieces - 1) / max_pieces), 0), phases - 1)


def piece_values(instream, stable_ply, keep_color, unpromoted, normalization, rescale, phases, max_pieces, imbalance):
    total = sum_line_count(instream)

    # collect data
    diffs = [[] for _ in range(phases)]
    results = [[] for _ in range(phases)]
    for epd in tqdm(instream, total=total):
        fen, annotations = parse_epd(epd)
        board = fen.split(' ')[0]
        hm = int(annotations.get('hmvc') or fen.split(' ')[-2])
        pieces = re.findall(r'[A-Za-z]' if unpromoted else r'(?:\+)?[A-Za-z]', board)
        num_board_pieces = len(re.findall(r'[A-Za-z]', board.split('[')[0]))
        if imbalance:
            for baseImbalance in imbalance:
                for colorImbalance in (baseImbalance, baseImbalance.swapcase()):
                    if has_imbalance(pieces, colorImbalance):
                        pieces.append(colorImbalance)
        result = annotations.get('result')
        if result in ('1-0', '0-1') and hm >= stable_ply:
            black_pov = fen.split(' ')[1] == 'b' and not keep_color
            pov_result = ('1-0' if result == '0-1' else '0-1') if black_pov else result
            phase = game_phase(phases, max_pieces, num_board_pieces)
            piece_set = set(min(p, p.swapcase()) for p in pieces)
            diffs[phase].append({p: (pieces.count(p) - pieces.count(p.swapcase())) * (-1 if black_pov else 1) for p in piece_set})
            results[phase].append(SCORE[pov_result])

    for i in range(phases):
        print('\nPhase {} of {}'.format(i + 1, phases))

        # convert to dataframe
        piece_diffs = pandas.DataFrame(diffs[i])
        piece_diffs.fillna(0, inplace=True)

        # fit
        model = LogisticRegression(solver='liblinear', C=10.0, random_state=0)
        model.fit(piece_diffs, results[i])

        # print fitted piece values
        if normalization == 'auto':
            norm = min(abs(v) for p, v in zip(piece_diffs.columns, model.coef_[0]) if len(p) == 1 and v > 0.05) / rescale
        elif normalization == 'natural':
            norm = log(10) / 2
        elif normalization == 'elo':
            norm = log(10) / 400
        else:
            norm = 1
        for p, v in sorted(zip(piece_diffs.columns, model.coef_[0]), key=lambda x: x[1], reverse=True):
            print(p, '{:.2f}'.format(v / norm))
        print('white' if keep_color else 'move', '{:.2f}'.format(model.intercept_[0] / norm))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('epd_files', nargs='*')
    parser.add_argument('-s', '--stable-ply', type=int, default=1, help='minimum ply since last material change')
    parser.add_argument('-c', '--keep-color', action='store_true', help='report color-specific statistics')
    parser.add_argument('-u', '--unpromoted', action='store_true', help='ignore promoted state of pieces')
    parser.add_argument('-i', '--imbalance', action='append', help='imbalance to evaluate. Can be specified more than once.')
    parser.add_argument('-n', '--normalization', choices=['off', 'elo', 'natural', 'auto'], default='auto', help='define normalization scale, one of %(choices)s')
    parser.add_argument('-r', '--rescale', type=float, default=1, help='rescale. only for "auto" normalization')
    parser.add_argument('-p', '--phases', type=int, default=1, help='number of game phases')
    parser.add_argument('-m', '--max-pieces', type=int, default=32, help='maximum number of pieces, for game phases')
    args = parser.parse_args()
    if args.rescale != 1 and args.normalization != 'auto':
        parser.error('Rescaling only supported for "auto" normalization.')

    with fileinput.input(args.epd_files) as instream:
        piece_values(instream, args.stable_ply, args.keep_color, args.unpromoted,
                     args.normalization, args.rescale, args.phases, args.max_pieces, args.imbalance)
